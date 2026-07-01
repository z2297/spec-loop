#!/usr/bin/env python3
"""Self-contained validator for a Claude Code plugin marketplace repo.

Validates that the marketplace and every plugin it references are structurally
sound, so a broken manifest can never ship to consumers. Standard library only.

Usage:
    python3 scripts/validate_marketplace.py [repo-root]   # defaults to cwd

Exit code 0 if everything is valid, 1 otherwise (with a printed list of errors).
"""

import json
import re
import sys
from pathlib import Path

KEBAB = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")

# A command is treated as read-only if any of these phrases appears in its text
# (frontmatter or prose). This is best-effort keyword detection — it raises the
# floor under the convention, it is not a sandbox: a command that grants Edit but
# avoids these phrases will not be caught. Read-only commands must not grant Edit.
READONLY_MARKERS = ("read-only", "read only", "never edits")


class Validator:
    def __init__(self, root: Path):
        self.root = root
        self.errors: list[str] = []

    def err(self, msg: str) -> None:
        self.errors.append(msg)

    def load_json(self, path: Path):
        """Parse JSON, recording an error (and returning None) on failure."""
        try:
            return json.loads(path.read_text())
        except FileNotFoundError:
            self.err(f"missing required file: {self._rel(path)}")
        except json.JSONDecodeError as e:
            self.err(f"invalid JSON in {self._rel(path)}: {e}")
        return None

    def _rel(self, path: Path) -> str:
        try:
            return str(path.relative_to(self.root))
        except ValueError:
            return str(path)

    def run(self) -> bool:
        marketplace_path = self.root / ".claude-plugin" / "marketplace.json"
        marketplace = self.load_json(marketplace_path)
        if marketplace is not None:
            self.validate_marketplace(marketplace)
        return not self.errors

    def validate_marketplace(self, m: dict) -> None:
        name = m.get("name")
        if not isinstance(name, str) or not KEBAB.match(name):
            self.err("marketplace.json: 'name' must be a kebab-case string")

        owner = m.get("owner")
        if not isinstance(owner, dict) or not owner.get("name"):
            self.err("marketplace.json: 'owner.name' is required")

        plugins = m.get("plugins")
        if not isinstance(plugins, list) or not plugins:
            self.err("marketplace.json: 'plugins' must be a non-empty array")
            return

        plugin_root = ""
        metadata = m.get("metadata")
        if isinstance(metadata, dict) and isinstance(metadata.get("pluginRoot"), str):
            plugin_root = metadata["pluginRoot"]

        seen_names: set[str] = set()
        for i, entry in enumerate(plugins):
            self.validate_plugin_entry(entry, i, plugin_root, seen_names)

    def validate_plugin_entry(self, entry, idx, plugin_root, seen_names) -> None:
        where = f"marketplace.json plugins[{idx}]"
        if not isinstance(entry, dict):
            self.err(f"{where}: must be an object")
            return

        name = entry.get("name")
        if not isinstance(name, str) or not KEBAB.match(name):
            self.err(f"{where}: 'name' must be a kebab-case string")
        else:
            where = f"plugin '{name}'"
            if name in seen_names:
                self.err(f"duplicate plugin name in marketplace: '{name}'")
            seen_names.add(name)

        source = entry.get("source")
        if not isinstance(source, str) or not source:
            # Object sources (github/url/git-subdir/npm) point outside this repo,
            # so there's nothing local to resolve — validate them structurally and
            # skip the path/frontmatter checks.
            if isinstance(source, dict):
                self.validate_source_object(where, source)
                return
            self.err(f"{where}: 'source' (relative path) is required")
            return

        if ".." in Path(source).parts:
            self.err(f"{where}: 'source' must not contain '..' (path traversal)")
            return

        rel = source
        if plugin_root and not source.startswith((".", "/")):
            rel = f"{plugin_root.rstrip('/')}/{source}"
        plugin_dir = (self.root / rel).resolve()

        if not plugin_dir.is_dir():
            self.err(f"{where}: source path does not resolve to a directory: {source}")
            return

        manifest_path = plugin_dir / ".claude-plugin" / "plugin.json"
        if not manifest_path.is_file():
            self.err(f"{where}: missing {self._rel(manifest_path)}")
            return

        self.validate_plugin(name, plugin_dir, manifest_path, entry)

    # Required keys per object-source type (see Claude Code marketplace docs).
    SOURCE_REQUIRED = {
        "github": ["repo"],
        "url": ["url"],
        "git-subdir": ["url", "path"],
        "npm": ["package"],
    }
    SHA = re.compile(r"^[0-9a-f]{40}$")

    def validate_source_object(self, where, source: dict) -> None:
        kind = source.get("source")
        if kind not in self.SOURCE_REQUIRED:
            self.err(
                f"{where}: 'source.source' must be one of "
                f"{sorted(self.SOURCE_REQUIRED)}, got {kind!r}"
            )
            return
        for key in self.SOURCE_REQUIRED[kind]:
            if not isinstance(source.get(key), str) or not source.get(key):
                self.err(f"{where}: {kind} source requires string '{key}'")
        if "ref" in source and not (isinstance(source["ref"], str) and source["ref"]):
            self.err(f"{where}: 'source.ref' must be a non-empty string")
        if "sha" in source and not self.SHA.match(str(source.get("sha", ""))):
            self.err(f"{where}: 'source.sha' must be a 40-char commit SHA")

    def validate_plugin(self, entry_name, plugin_dir, manifest_path, entry) -> None:
        manifest = self.load_json(manifest_path)
        if manifest is None:
            return

        where = f"{self._rel(manifest_path)}"
        pname = manifest.get("name")
        if not isinstance(pname, str) or not KEBAB.match(pname):
            self.err(f"{where}: 'name' must be a kebab-case string")
        elif entry_name and pname != entry_name:
            self.err(
                f"{where}: name '{pname}' does not match marketplace entry "
                f"'{entry_name}'"
            )

        entry_version = entry.get("version")
        manifest_version = manifest.get("version")
        if entry_version and manifest_version and entry_version != manifest_version:
            self.err(
                f"plugin '{entry_name}': version mismatch — marketplace "
                f"'{entry_version}' vs plugin.json '{manifest_version}'"
            )

        self.validate_frontmatter_files(plugin_dir)

    def validate_frontmatter_files(self, plugin_dir: Path) -> None:
        # skills/<name>/SKILL.md -> name + description; name must match dir
        for skill in sorted(plugin_dir.glob("skills/*/SKILL.md")):
            fm = self.read_frontmatter(skill)
            if fm is None:
                continue
            self.require_keys(skill, fm, ["name", "description"])
            declared = fm.get("name")
            dirname = skill.parent.name
            if declared and declared != dirname:
                self.err(
                    f"{self._rel(skill)}: frontmatter name '{declared}' does not "
                    f"match its directory '{dirname}'"
                )

        for cmd in sorted(plugin_dir.glob("commands/*.md")):
            fm = self.read_frontmatter(cmd)
            if fm is None:
                continue
            self.require_keys(cmd, fm, ["description"])
            self.check_readonly_no_edit(cmd, fm)

        for agent in sorted(plugin_dir.glob("agents/*.md")):
            fm = self.read_frontmatter(agent)
            if fm is None:
                continue
            self.require_keys(agent, fm, ["name", "description"])

    def check_readonly_no_edit(self, cmd: Path, fm: dict) -> None:
        """A command marked read-only (by frontmatter or prose) must not grant
        `Edit` in its `allowed-tools`. Detection is best-effort keyword matching;
        the Edit check reads the frontmatter value only, so prose that merely
        mentions Edit (e.g. 'allowed-tools excludes Edit') is not a false positive."""
        text = cmd.read_text().lower()
        if not any(marker in text for marker in READONLY_MARKERS):
            return
        tools = self._allowed_tools(fm)
        if "Edit" in tools:
            self.err(
                f"{self._rel(cmd)}: command is marked read-only but its "
                f"'allowed-tools' grants 'Edit'"
            )

    @staticmethod
    def _allowed_tools(fm: dict) -> set[str]:
        """Extract the quoted tool tokens from a frontmatter `allowed-tools` value
        (a one-line JSON-ish array). Returns an empty set when absent/unparsable."""
        raw = fm.get("allowed-tools")
        if not isinstance(raw, str):
            return set()
        return set(re.findall(r'"([^"]+)"', raw))

    @staticmethod
    def _frontmatter_value_error(key: str, value: str) -> str | None:
        """Targeted heuristic for the one YAML-frontmatter breakage class that this
        regex parser would otherwise miss: an UNQUOTED top-level scalar containing
        ': ' (colon-space). Real YAML reads that as a nested mapping and rejects it
        in scalar position, so a value like `description: do X: then Y` loads empty
        (or errors) under the authoritative `claude plugin validate` while passing a
        naive key-presence check. Quoting the value is exactly the fix YAML wants,
        so a value wrapped in MATCHING single/double quotes is always safe — even
        when it contains ': '.

        `value` is the already-trailing-stripped capture from read_frontmatter (the
        line regex consumes leading whitespace, and .strip() removes trailing spaces
        and any CRLF \\r), which keeps the quote check robust on CRLF-checked-out
        files. Returns an error string naming the key, or None when the value is fine.

        This is deliberately NOT a YAML parser: it catches only the colon-space class
        that actually shipped past this gate. Other YAML-rejection classes (e.g. a
        bare leading '[' opening a flow sequence, quoted-then-trailing content like
        '"x" y', duplicate keys) are left to CI's `claude plugin validate`, which
        remains the authoritative frontmatter gate. An empty value is left to the
        existing require_keys presence check, not flagged here."""
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            return None  # properly quoted -> safe, even if it contains ': '
        if ": " in value:
            return (
                f"frontmatter value for '{key}' contains ': ' and must be quoted "
                f"(unquoted YAML reads it as a nested mapping; "
                f"CI's `claude plugin validate` rejects it)"
            )
        return None

    def read_frontmatter(self, path: Path):
        """Return a dict of top-level frontmatter keys, or None (recording an
        error) if the leading --- block is missing. Minimal parser: top-level
        'key:' lines only — enough to assert required keys are present, plus a
        targeted check (via _frontmatter_value_error) for the unquoted-colon-space
        value class that real YAML rejects but key-presence parsing would miss."""
        text = path.read_text()
        if not text.startswith("---"):
            self.err(f"{self._rel(path)}: missing YAML frontmatter (--- block)")
            return None
        end = text.find("\n---", 3)
        if end == -1:
            self.err(f"{self._rel(path)}: unterminated frontmatter block")
            return None
        block = text[3:end]
        keys: dict[str, str] = {}
        for line in block.splitlines():
            # only top-level keys (no leading whitespace), of the form key: value
            m = re.match(r"^([A-Za-z0-9_-]+):\s*(.*)$", line)
            if m:
                key, value = m.group(1), m.group(2).strip()
                keys[key] = value
                value_err = self._frontmatter_value_error(key, value)
                if value_err:
                    self.err(f"{self._rel(path)}: {value_err}")
        return keys

    def require_keys(self, path: Path, fm: dict, keys: list[str]) -> None:
        for key in keys:
            if not fm.get(key):
                self.err(f"{self._rel(path)}: frontmatter missing required '{key}'")


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    root = Path(argv[0] if argv else ".").resolve()
    if not root.is_dir():
        print(f"error: not a directory: {root}", file=sys.stderr)
        return 1

    v = Validator(root)
    ok = v.run()
    if ok:
        print(f"OK: marketplace and all plugins valid ({v._rel(root)})")
        return 0

    print(f"FAILED: {len(v.errors)} error(s) found:", file=sys.stderr)
    for e in v.errors:
        print(f"  - {e}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())

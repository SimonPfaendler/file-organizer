#!/usr/bin/env python3
"""
Datei-Organizer – ein einfacher, robuster CLI-Datei-Organizer für den Einstieg.

Features:
- Ordnet Dateien aus einem Quellordner in einen Zielordner nach Regeln (z. B. Endungen)
- Modi: move (verschieben) oder copy (kopieren)
- Rekursiv, Dry-Run, Protokoll (Manifest) & Undo-Funktion
- Konfliktlösung (automatisches Umbenennen)
- Konfigurierbare Regeln via JSON/YAML (optional)
- Optional nach Datum (Jahr/Monat) einsortieren

Beispiele:
    python file_organizer.py /Pfad/Quelle /Pfad/Ziel --mode move --recursive --dry-run
    python file_organizer.py ~/Downloads ~/Sortiert --mode move --rules rules.json
    python file_organizer.py ~/DL ~/Sortiert --mode copy --by-date
    python file_organizer.py --undo manifest_2025-10-08T12-00-00.json

Regeldatei (JSON) Beispiel:
{
    ".jpg": "Bilder",
    ".jpeg": "Bilder",
    ".png": "Bilder",
    ".gif": "Bilder",
    ".webp": "Bilder",
  
    ".pdf": "PDF",
    ".doc": "Dokumente",
    ".docx": "Dokumente",
    ".txt": "Text",
    ".md": "Markdown",
    ".ppt": "Präsentationen",
    ".pptx": "Präsentationen",
    ".xls": "Tabellen",
    ".xlsx": "Tabellen",
    ".csv": "Tabellen",
  
    ".mp3": "Audio",
    ".wav": "Audio",
    ".flac": "Audio",
  
    ".mp4": "Videos",
    ".mov": "Videos",
    ".mkv": "Videos",
  
    ".zip": "Archive",
    ".rar": "Archive",
    ".7z": "Archive",
  
    ".py": "Code",
    ".js": "Code",
    ".ts": "Code"
  }

Hinweise:
- Das Manifest erlaubt Undo: Verschobenes wird zurückverschoben, Kopiertes gelöscht.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import mimetypes
import os
from pathlib import Path
import shutil
import sys
from typing import Dict, List, Optional, Tuple


# ---------------------- Standard-Regeln (Fallback) ---------------------- #
DEFAULT_RULES: Dict[str, str] = {
    # Bilder
    ".jpg": "Bilder", ".jpeg": "Bilder", ".png": "Bilder", ".gif": "Bilder", ".webp": "Bilder",
    # Dokumente
    ".pdf": "PDF", ".doc": "Dokumente", ".docx": "Dokumente", ".txt": "Text",
    ".md": "Markdown", ".ppt": "Präsentationen", ".pptx": "Präsentationen", ".xls": "Tabellen", ".xlsx": "Tabellen", ".csv": "Tabellen",
    # Audio / Video
    ".mp3": "Audio", ".wav": "Audio", ".flac": "Audio",
    ".mp4": "Videos", ".mov": "Videos", ".mkv": "Videos",
    # Code / Archive / Sonstiges
    ".py": "Code", ".js": "Code", ".ts": "Code",
    ".zip": "Archive", ".rar": "Archive", ".7z": "Archive",
}

# ---------------------- Hilfsfunktionen ---------------------- #

def load_rules(path: Optional[Path]) -> Dict[str, str]:
    if path is None:
        return DEFAULT_RULES.copy()
    if not path.exists():
        raise FileNotFoundError(f"Regeldatei nicht gefunden: {path}")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    # Normalisiere Keys zu .ext Kleinbuchstaben
    rules: Dict[str, str] = {}
    for k, v in data.items():
        if not k.startswith("."):
            k = "." + k
        rules[k.lower()] = str(v)
    return rules


def hash_file(path: Path, chunk_size: int = 1 << 20) -> str:
    sha = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            sha.update(chunk)
    return sha.hexdigest()[:12]


def infer_category(p: Path, rules: Dict[str, str]) -> str:
    ext = p.suffix.lower()
    if ext in rules:
        return rules[ext]
    # Fallback via MIME-Typ
    mime, _ = mimetypes.guess_type(str(p))
    if mime:
        major = mime.split("/", 1)[0]
        mapping = {"image": "Bilder", "audio": "Audio", "video": "Videos", "text": "Text"}
        if major in mapping:
            return mapping[major]
    return "Sonstiges"


def build_target_path(
    src_file: Path,
    dest_root: Path,
    category: str,
    by_date: bool,
) -> Path:
    parts = [dest_root, Path(category)]
    if by_date:
        try:
            mtime = dt.datetime.fromtimestamp(src_file.stat().st_mtime)
        except Exception:
            mtime = dt.datetime.now()
        parts.extend([Path(str(mtime.year)), Path(f"{mtime.month:02d}")])
    target_dir = Path(*parts)
    target_dir.mkdir(parents=True, exist_ok=True)
    return target_dir / src_file.name


def resolve_conflict(target: Path, strategy: str = "rename") -> Path:
    if not target.exists():
        return target
    if strategy == "skip":
        return target  # Caller muss dann skippen
    stem, suffix = target.stem, target.suffix
    parent = target.parent
    i = 1
    while True:
        candidate = parent / f"{stem} ({i}){suffix}"
        if not candidate.exists():
            return candidate
        i += 1


def move_or_copy(src: Path, dst: Path, mode: str) -> None:
    if mode == "move":
        shutil.move(str(src), str(dst))
    elif mode == "copy":
        shutil.copy2(str(src), str(dst))
    else:
        raise ValueError("mode muss 'move' oder 'copy' sein")


# ---------------------- Manifest / Undo ---------------------- #

def manifest_filename(prefix: str = "manifest") -> str:
    ts = dt.datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    return f"{prefix}_{ts}.json"


def write_manifest(path: Path, records: List[Dict]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)


def read_manifest(path: Path) -> List[Dict]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def undo_from_manifest(manifest_path: Path, verbose: bool = True) -> None:
    records = read_manifest(manifest_path)
    errors = 0
    for rec in records:
        action = rec.get("action")
        src = Path(rec.get("src"))
        dst = Path(rec.get("dst"))
        mode = rec.get("mode")
        existed = rec.get("dst_existed", False)

        if action != "transfer":
            continue
        try:
            if mode == "move":
                # zurückverschieben, falls vorhanden
                if dst.exists():
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(dst), str(src))
                else:
                    print(f"[WARN] Ziel fehlt, kann nicht zurückbewegen: {dst}")
            elif mode == "copy":
                # Kopie löschen
                if dst.exists():
                    dst.unlink()
                else:
                    print(f"[WARN] Kopie fehlt, kann nicht löschen: {dst}")
            else:
                print(f"[WARN] Unbekannter Modus im Manifest: {mode}")
        except Exception as e:
            errors += 1
            print(f"[ERROR] Undo fehlgeschlagen für {dst} -> {src}: {e}")
    if verbose:
        if errors:
            print(f"Undo beendet mit {errors} Fehler(n).")
        else:
            print("Undo vollständig abgeschlossen.")


# ---------------------- Hauptlogik ---------------------- #

def collect_files(root: Path, recursive: bool) -> List[Path]:
    if recursive:
        return [p for p in root.rglob("*") if p.is_file()]
    else:
        return [p for p in root.glob("*") if p.is_file()]


def organize(
    source: Path,
    dest: Path,
    mode: str = "move",
    recursive: bool = True,
    dry_run: bool = False,
    rules_path: Optional[Path] = None,
    by_date: bool = False,
    conflict: str = "rename",  # oder "skip"
    write_manifest_to: Optional[Path] = None,
) -> Path:
    if mode not in {"move", "copy"}:
        raise ValueError("mode muss 'move' oder 'copy' sein")
    if conflict not in {"rename", "skip"}:
        raise ValueError("conflict muss 'rename' oder 'skip' sein")

    rules = load_rules(rules_path)
    files = collect_files(source, recursive)

    manifest_records: List[Dict] = []
    transfers = 0

    for f in files:
        category = infer_category(f, rules)
        target = build_target_path(f, dest, category, by_date)

        final_target = target
        if final_target.exists():
            # Prüfe Duplikate via Größe + Hash (leichtgewichtige Heuristik)
            try:
                if f.stat().st_size == final_target.stat().st_size:
                    # Wenn gleiche Größe, optional Hash vergleichen
                    if hash_file(f) == hash_file(final_target):
                        # identische Datei – überspringen
                        print(f"[SKIP] Duplikat erkannt: {f} == {final_target}")
                        continue
            except Exception:
                pass
            if conflict == "skip":
                print(f"[SKIP] Existiert bereits: {final_target}")
                continue
            final_target = resolve_conflict(final_target, strategy="rename")

        print(f"[PLAN] {mode.upper()} {f} -> {final_target}")
        if not dry_run:
            try:
                move_or_copy(f, final_target, mode)
                transfers += 1
                manifest_records.append({
                    "action": "transfer",
                    "mode": mode,
                    "src": str(f.resolve()),
                    "dst": str(final_target.resolve()),
                    "category": category,
                    "by_date": by_date,
                    "dst_existed": target.exists(),
                })
            except Exception as e:
                print(f"[ERROR] Übertragung fehlgeschlagen: {f} -> {final_target}: {e}")

    if write_manifest_to is None:
        write_manifest_to = dest / manifest_filename()

    if not dry_run:
        try:
            write_manifest(write_manifest_to, manifest_records)
            print(f"[OK] Manifest geschrieben: {write_manifest_to} ({len(manifest_records)} Einträge)")
        except Exception as e:
            print(f"[WARN] Konnte Manifest nicht schreiben: {e}")
    else:
        print("[INFO] Dry-Run: keine Änderungen durchgeführt, kein Manifest geschrieben.")

    print(f"[DONE] Geplante/ausgeführte Transfers: {transfers} von {len(files)} Dateien")
    return write_manifest_to


# ---------------------- CLI ---------------------- #

def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Datei-Organizer: ordnet Dateien nach Regeln in Zielordner ein.")
    group = p.add_mutually_exclusive_group(required=False)
    group.add_argument("--undo", type=str, help="Manifest-Datei laden und Aktionen rückgängig machen.")

    p.add_argument("source", nargs="?", help="Quellordner mit Dateien.")
    p.add_argument("dest", nargs="?", help="Zielordner für organisiertes Ablagesystem.")
    p.add_argument("--mode", choices=["move", "copy"], default="move", help="move=verschieben, copy=kopieren (Standard: move)")
    p.add_argument("--recursive", action="store_true", help="rekursiv durch Unterordner laufen")
    p.add_argument("--dry-run", action="store_true", help="nur anzeigen, was passieren würde")
    p.add_argument("--rules", type=str, help="Pfad zu Regeln (JSON oder YAML)")
    p.add_argument("--by-date", action="store_true", help="zusätzlich nach Jahr/Monat ablegen")
    p.add_argument("--conflict", choices=["rename", "skip"], default="rename", help="Konfliktstrategie bei vorhandenen Dateien")
    p.add_argument("--manifest-out", type=str, help="Pfad/Dateiname für Manifest")

    args = p.parse_args(argv)

    # Validierung: entweder Undo ODER normaler Lauf
    if args.undo:
        return args

    if not args.source or not args.dest:
        p.error("Bitte Quelle und Ziel angeben (oder --undo verwenden).")

    return args


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)

    if args.undo:
        mpath = Path(args.undo)
        if not mpath.exists():
            print(f"Manifest nicht gefunden: {mpath}")
            return 2
        undo_from_manifest(mpath)
        return 0

    source = Path(args.source).expanduser().resolve()
    dest = Path(args.dest).expanduser().resolve()

    if not source.exists() or not source.is_dir():
        print(f"Quelle existiert nicht oder ist kein Ordner: {source}")
        return 2
    dest.mkdir(parents=True, exist_ok=True)

    rules_path = Path(args.rules).expanduser().resolve() if args.rules else None
    manifest_out = Path(args.manifest_out) if args.manifest_out else None

    try:
        manifest_path = organize(
            source=source,
            dest=dest,
            mode=args.mode,
            recursive=args.recursive,
            dry_run=args.dry_run,
            rules_path=rules_path,
            by_date=args.by_date,
            conflict=args.conflict,
            write_manifest_to=manifest_out,
        )
        if args.dry_run:
            print("Dry-Run abgeschlossen. Wenn es gut aussieht, entferne --dry-run.")
        else:
            print(f"Fertig. Manifest unter: {manifest_path}")
        return 0
    except Exception as e:
        print(f"Fehler: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())

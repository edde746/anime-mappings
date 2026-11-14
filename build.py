"""Build anime-mappings.bin.gz, a packed list of Fribb's anime-list-mini.json and Anime-Lists' anime-list.xml.

The packed list holds everything both files carry but the keys FRIBB_DROPPED names (Fribb's `anime-planet_id`), as a
Trave file (the README's "The format"). The builder knows every key, attribute and element of both files and stops on
any other one, so new upstream data stops a release instead of being dropped. The output is the same bytes for the
same input.

Usage:
  python build.py FRIBB_JSON ANIME_LISTS_XML OUT [--check]   build OUT (gzip), and with --check read it back and
                                                              compare it field by field with both inputs
  python build.py --dump OUT                                  print OUT's tables and columns with their sizes
Python 3.9 or newer, plus trave (pip install -r requirements.txt).
"""
import argparse
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import trave

MAGIC = b"AMAP"

INT64 = range(-(2**63) + 1, 2**63)  # Trave's int range: a signed 64-bit integer above -2**63
DECIMAL = re.compile(r"-?(0|[1-9][0-9]*)")


class Unknown(Exception):
    """Upstream data the builder doesn't know: a key, attribute, element or value of a shape it doesn't handle."""


# Fribb: column name -> type, in the file's column order. A dotted name is a key of a nested object.
FRIBB_COLUMNS = {
    "type": trave.DICT,
    "anidb_id": trave.INT_DELTA,
    "mal_id": trave.INT_DELTA,
    "kitsu_id": trave.INT_DELTA,
    "anisearch_id": trave.INT_DELTA,
    "anilist_id": trave.INT_DELTA,
    "animecountdown_id": trave.INT_DELTA,
    "simkl_id": trave.INT_DELTA,
    "animenewsnetwork_id": trave.INT_DELTA,
    "livechart_id": trave.INT_DELTA,
    "themoviedb_id.tv": trave.INT,
    "themoviedb_id.movie": trave.INT_LIST,
    "imdb_id": trave.STR_LIST,
    "tvdb_id": trave.INT,
    "season.tvdb": trave.INT,
    "season.tmdb": trave.INT,
    "episode_offset.tvdb": trave.INT,
    "episode_offset.tmdb": trave.INT,
}
FRIBB_OBJECTS = {"themoviedb_id": ("tv", "movie"), "season": ("tvdb", "tmdb"), "episode_offset": ("tvdb", "tmdb")}
# Fribb keys left out on purpose; Fribb's own files have them. Anime-Planet's string slugs were a third of the file.
FRIBB_DROPPED = ("anime-planet_id",)

# Anime-Lists' <anime> attributes. A "number or word" attribute is two columns: `<name>` holds a decimal value as
# an int, `<name>_text` (a dict) any other value. A "list" attribute is a comma-separated list.
ANIME_ATTRIBUTES = {
    "anidbid": "number",
    "tvdbid": "number or word",
    "defaulttvdbseason": "number or word",
    "episodeoffset": "number",
    "tmdbtv": "number",
    "tmdbseason": "number or word",
    "tmdboffset": "number",
    "tmdbid": "number list",
    "imdbid": "text list",
}
MAPPING_ATTRIBUTES = ("anidbseason", "tvdbseason", "tmdbseason", "start", "end", "offset")
SUPPLEMENTAL_TEXT = ("studio", "genre", "director", "credits")
THUMB_ATTRIBUTES = ("dim", "colors", "preview")
# The elements of an <anime>, in the order they must come in.
ANIME_CHILDREN = ("name", "mapping-list", "before", "supplemental-info")


# --- Fribb -----------------------------------------------------------------------------------------------------------

def integer(value, where):
    if type(value) is not int or value not in INT64:
        raise Unknown(f"{where}: {value!r} is not a 64-bit integer above -2**63")
    return value


def string(value, where):
    if type(value) is not str:
        raise Unknown(f"{where}: {value!r} is not a string")
    return value


def fribb_columns(rows):
    if type(rows) is not list:
        raise Unknown("Fribb: the document is not an array")
    values = {name: [] for name in FRIBB_COLUMNS}
    for i, row in enumerate(rows):
        where = f"Fribb row {i}"
        if type(row) is not dict:
            raise Unknown(f"{where}: not an object")
        flat = {}
        for key, value in row.items():
            if key in FRIBB_OBJECTS:
                if type(value) is not dict or not value:
                    raise Unknown(f"{where}.{key}: {value!r} is not a non-empty object")
                for sub, v in value.items():
                    if sub not in FRIBB_OBJECTS[key]:
                        raise Unknown(f"{where}.{key}: unknown key {sub!r}")
                    flat[f"{key}.{sub}"] = v
            elif key in FRIBB_COLUMNS:
                flat[key] = value
            elif key in FRIBB_DROPPED:
                continue
            else:
                raise Unknown(f"{where}: unknown key {key!r}")
        for name, kind in FRIBB_COLUMNS.items():
            v = flat.get(name)
            here = f"{where}.{name}"
            if v is None:
                if name in flat:
                    raise Unknown(f"{here}: null")
            elif kind in (trave.INT, trave.INT_DELTA):
                integer(v, here)
            elif kind in (trave.STR, trave.DICT):
                string(v, here)
            elif kind == trave.INT_LIST:
                if type(v) is not list:
                    raise Unknown(f"{here}: {v!r} is not an array")
                for x in v:
                    integer(x, here)
            elif kind == trave.STR_LIST:
                if type(v) is not list:
                    raise Unknown(f"{here}: {v!r} is not an array")
                for x in v:
                    string(x, here)
            values[name].append(v)
    return [(name, kind, values[name]) for name, kind in FRIBB_COLUMNS.items()]


# --- Anime-Lists -----------------------------------------------------------------------------------------------------

def blank(s):
    return s is None or s.strip() == ""


def no_attributes(e, where):
    if e.attrib:
        raise Unknown(f"{where}: unknown attribute(s) {sorted(e.attrib)} on <{e.tag}>")


def only_elements(e, where):
    """A container's text and its children's tails are layout only."""
    if not blank(e.text) or any(not blank(c.tail) for c in e):
        raise Unknown(f"{where}: text inside <{e.tag}>")


def leaf(e, where):
    """A text element: no attributes, no children; its text verbatim (None when empty)."""
    no_attributes(e, where)
    if len(e):
        raise Unknown(f"{where}: unknown element <{e[0].tag}> in <{e.tag}>")
    return e.text


def number(value, where):
    if not DECIMAL.fullmatch(value) or int(value) not in INT64:
        raise Unknown(f"{where}: {value!r} is not a decimal 64-bit integer above -2**63")
    return int(value)


def anime_lists_tables(root):
    if root.tag != "anime-list":
        raise Unknown(f"Anime-Lists: the root is <{root.tag}>, not <anime-list>")
    no_attributes(root, "Anime-Lists")
    only_elements(root, "Anime-Lists")

    anime = {}
    for attr, kind in ANIME_ATTRIBUTES.items():
        anime[attr] = []
        if kind == "number or word":
            anime[attr + "_text"] = []
    anime["name"], anime["before"] = [], []
    mappings = {"anidbid": [], **{a: [] for a in MAPPING_ATTRIBUTES}, "text": []}
    supplemental = {"anidbid": [], "block": [], "replace": [], "element": [], "text": [], **{a: [] for a in THUMB_ATTRIBUTES}}
    seen = set()

    for i, e in enumerate(root):
        where = f"Anime-Lists <anime> {i}"
        if e.tag != "anime":
            raise Unknown(f"{where}: unknown element <{e.tag}>")
        only_elements(e, where)
        for attr in e.attrib:
            if attr not in ANIME_ATTRIBUTES:
                raise Unknown(f"{where}: unknown attribute {attr!r}")
        if "anidbid" not in e.attrib:
            raise Unknown(f"{where}: no anidbid")
        anidb = number(e.attrib["anidbid"], f"{where} anidbid")
        if anidb in seen:
            raise Unknown(f"{where}: anidbid {anidb} again (it is the key of the mappings and supplemental info)")
        seen.add(anidb)
        where = f"Anime-Lists anidbid {anidb}"
        for attr, kind in ANIME_ATTRIBUTES.items():
            v = e.attrib.get(attr)
            if kind == "number":
                anime[attr].append(None if v is None else number(v, f"{where} {attr}"))
            elif kind == "number or word":
                is_number = v is not None and DECIMAL.fullmatch(v) is not None and int(v) in INT64
                anime[attr].append(int(v) if is_number else None)
                anime[attr + "_text"].append(None if v is None or is_number else v)
            elif kind == "number list":
                anime[attr].append(None if v is None else [number(x, f"{where} {attr}") for x in v.split(",")])
            else:
                anime[attr].append(None if v is None else v.split(","))

        order = [ANIME_CHILDREN.index(c.tag) if c.tag in ANIME_CHILDREN else -1 for c in e]
        if -1 in order:
            raise Unknown(f"{where}: unknown element <{e[order.index(-1)].tag}>")
        if order != sorted(order):
            raise Unknown(f"{where}: elements {[c.tag for c in e]} not in the order {list(ANIME_CHILDREN)}")
        for tag in ("name", "mapping-list", "before"):
            if order.count(ANIME_CHILDREN.index(tag)) > 1:
                raise Unknown(f"{where}: <{tag}> more than once")
        names = e.findall("name")
        if len(names) != 1:
            raise Unknown(f"{where}: no <name>")
        anime["name"].append(leaf(names[0], where))
        before = e.find("before")
        anime["before"].append(None if before is None else leaf(before, where))

        mapping_list = e.find("mapping-list")
        if mapping_list is not None:
            no_attributes(mapping_list, where)
            only_elements(mapping_list, where)
            if not len(mapping_list):
                raise Unknown(f"{where}: an empty <mapping-list>")
            for m in mapping_list:
                if m.tag != "mapping":
                    raise Unknown(f"{where}: unknown element <{m.tag}> in <mapping-list>")
                if len(m):
                    raise Unknown(f"{where}: unknown element <{m[0].tag}> in <mapping>")
                for attr in m.attrib:
                    if attr not in MAPPING_ATTRIBUTES:
                        raise Unknown(f"{where}: unknown <mapping> attribute {attr!r}")
                mappings["anidbid"].append(anidb)
                for attr in MAPPING_ATTRIBUTES:
                    v = m.attrib.get(attr)
                    mappings[attr].append(None if v is None else number(v, f"{where} <mapping> {attr}"))
                mappings["text"].append(m.text)

        for block, info in enumerate(e.findall("supplemental-info")):
            for attr in info.attrib:
                if attr != "replace":
                    raise Unknown(f"{where}: unknown <supplemental-info> attribute {attr!r}")
            only_elements(info, where)
            if not len(info):
                raise Unknown(f"{where}: an empty <supplemental-info>")
            for item in info:
                thumb = {a: None for a in THUMB_ATTRIBUTES}
                if item.tag in SUPPLEMENTAL_TEXT:
                    value = leaf(item, where)
                elif item.tag == "fanart":
                    no_attributes(item, where)
                    only_elements(item, where)
                    if len(item) != 1 or item[0].tag != "thumb":
                        raise Unknown(f"{where}: <fanart> holds {[c.tag for c in item]}, not one <thumb>")
                    t = item[0]
                    for attr in t.attrib:
                        if attr not in THUMB_ATTRIBUTES:
                            raise Unknown(f"{where}: unknown <thumb> attribute {attr!r}")
                    if len(t):
                        raise Unknown(f"{where}: unknown element <{t[0].tag}> in <thumb>")
                    thumb = {a: t.attrib.get(a) for a in THUMB_ATTRIBUTES}
                    value = t.text
                else:
                    raise Unknown(f"{where}: unknown element <{item.tag}> in <supplemental-info>")
                supplemental["anidbid"].append(anidb)
                supplemental["block"].append(block)
                supplemental["replace"].append(info.attrib.get("replace"))
                supplemental["element"].append(item.tag)
                supplemental["text"].append(value)
                for a in THUMB_ATTRIBUTES:
                    supplemental[a].append(thumb[a])

    anime_types = {}
    for attr, kind in ANIME_ATTRIBUTES.items():
        anime_types[attr] = {"number": trave.INT, "number or word": trave.INT, "number list": trave.INT_LIST,
                             "text list": trave.STR_LIST}[kind]
        if kind == "number or word":
            anime_types[attr + "_text"] = trave.DICT
    anime_types["anidbid"] = trave.INT_DELTA
    anime_types["name"], anime_types["before"] = trave.STR, trave.STR
    mapping_types = {"anidbid": trave.INT_DELTA, **{a: trave.INT for a in MAPPING_ATTRIBUTES}, "text": trave.STR}
    supplemental_types = {"anidbid": trave.INT_DELTA, "block": trave.INT, "replace": trave.DICT, "element": trave.DICT,
                          "text": trave.STR, "dim": trave.DICT, "colors": trave.DICT, "preview": trave.STR}
    rows = len(anime["anidbid"])
    return [
        ("anime_lists", rows, [(n, anime_types[n], v) for n, v in anime.items()]),
        ("anime_lists_mappings", len(mappings["anidbid"]), [(n, mapping_types[n], v) for n, v in mappings.items()]),
        ("anime_lists_supplemental", len(supplemental["anidbid"]),
         [(n, supplemental_types[n], v) for n, v in supplemental.items()]),
    ]


# --- building --------------------------------------------------------------------------------------------------------

def build(fribb_path, anime_lists_path):
    """Both files as the packed list's bytes (not gzipped)."""
    rows = json.loads(Path(fribb_path).read_bytes())
    fribb = ("fribb", len(rows) if type(rows) is list else 0, fribb_columns(rows))
    root = ET.parse(anime_lists_path).getroot()
    return trave.pack(MAGIC, [fribb, *anime_lists_tables(root)])


# --- reading back -----------------------------------------------------------------------------------------------------

def fribb_rows(tables):
    """The Fribb table as anime-list-mini.json's rows."""
    rows, columns = tables["fribb"]
    out = [{} for _ in range(rows)]
    for name, values in columns.items():
        for row, v in zip(out, values):
            if v is None:
                continue
            if "." in name:
                key, sub = name.split(".")
                row.setdefault(key, {})[sub] = v
            else:
                row[name] = v
    return out


def anime_lists_tree(tables):
    """The three Anime-Lists tables as canonical(<anime-list>) of the XML they were built from."""
    rows, anime = tables["anime_lists"]
    _, mappings = tables["anime_lists_mappings"]
    _, supplemental = tables["anime_lists_supplemental"]

    def grouped(columns):
        by_anidb = {}
        for i, anidb in enumerate(columns["anidbid"]):
            by_anidb.setdefault(anidb, []).append({n: v[i] for n, v in columns.items()})
        return by_anidb

    mapping_rows, supplemental_rows = grouped(mappings), grouped(supplemental)
    out = []
    for i in range(rows):
        attrib = {}
        for attr, kind in ANIME_ATTRIBUTES.items():
            v = anime[attr][i]
            if kind == "number or word" and v is None:
                v = anime[attr + "_text"][i]
            elif kind in ("number list", "text list") and v is not None:
                v = ",".join(map(str, v))
            if v is not None:
                attrib[attr] = str(v)
        anidb = anime["anidbid"][i]
        children = [("name", {}, anime["name"][i], [])]
        if anidb in mapping_rows:
            children.append(("mapping-list", {}, None, [
                ("mapping", {a: str(m[a]) for a in MAPPING_ATTRIBUTES if m[a] is not None}, m["text"], [])
                for m in mapping_rows[anidb]
            ]))
        if anime["before"][i] is not None:
            children.append(("before", {}, anime["before"][i], []))
        blocks = {}
        for s in supplemental_rows.get(anidb, []):
            attrib_info = {} if s["replace"] is None else {"replace": s["replace"]}
            items = blocks.setdefault(s["block"], (attrib_info, []))[1]
            if s["element"] == "fanart":
                thumb = {a: s[a] for a in THUMB_ATTRIBUTES if s[a] is not None}
                items.append(("fanart", {}, None, [("thumb", thumb, s["text"], [])]))
            else:
                items.append((s["element"], {}, s["text"], []))
        for block in sorted(blocks):
            children.append(("supplemental-info", blocks[block][0], None, blocks[block][1]))
        out.append(("anime", attrib, None, children))
    return ("anime-list", {}, None, out)


def canonical(e):
    """An element as (tag, attributes, text, children), a container's layout whitespace as no text."""
    t = e.text if len(e) == 0 else (None if blank(e.text) else e.text)
    return (e.tag, dict(e.attrib), t, [canonical(c) for c in e])


# --- command line ----------------------------------------------------------------------------------------------------

def check(out, fribb_path, anime_lists_path):
    tables = trave.read(Path(out).read_bytes(), MAGIC)
    expected = json.loads(Path(fribb_path).read_bytes())
    actual = fribb_rows(tables)
    if len(actual) != len(expected):
        raise SystemExit(f"check: {len(actual)} Fribb rows read back, {len(expected)} upstream")
    for i, (a, x) in enumerate(zip(actual, expected)):
        x = {k: v for k, v in x.items() if k not in FRIBB_DROPPED}
        if a != x:
            raise SystemExit(f"check: Fribb row {i} reads back as {a}, upstream {x}")
    fribb = len(actual)
    expected = canonical(ET.parse(anime_lists_path).getroot())
    actual = anime_lists_tree(tables)
    if len(actual[3]) != len(expected[3]):
        raise SystemExit(f"check: {len(actual[3])} <anime> read back, {len(expected[3])} upstream")
    for a, x in zip(actual[3], expected[3]):
        if a != x:
            raise SystemExit(f"check: <anime> reads back as {a}, upstream {x}")
    if actual != expected:
        raise SystemExit("check: <anime-list> differs")
    print(f"checked: {fribb:,} Fribb rows and {len(expected[3]):,} <anime> read back the same", flush=True)


def dump(path):
    data = Path(path).read_bytes()
    try:
        raw = trave.unpack(data)
        trave.read(raw, MAGIC)  # the whole file is valid before anything is printed
    except ValueError as e:
        raise SystemExit(f"{path}: {e}")
    print(f"{path}: {len(data):,} bytes, {len(raw):,} unpacked")
    r = trave.Reader(raw, 5)
    for _ in range(r.varint()):
        name, rows = r.text(), r.varint()
        print(f"{name}: {rows:,} rows")
        for _ in range(r.varint()):
            cname, kind, length = r.text(), r.byte(), r.varint()
            r.bytes(length)
            print(f"  {cname:24} {trave.TYPE_NAMES.get(kind, kind):10} {length:>9,} bytes")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("inputs", nargs="*", type=Path)
    p.add_argument("--check", action="store_true", help="read OUT back and compare it with both inputs")
    p.add_argument("--dump", type=Path, help="print a packed list's tables and columns")
    a = p.parse_args()
    if a.dump:
        dump(a.dump)
        return
    if len(a.inputs) != 3:
        p.error("FRIBB_JSON ANIME_LISTS_XML OUT expected")
    fribb, anime_lists, out = a.inputs
    try:
        data = build(fribb, anime_lists)
    except Unknown as e:
        raise SystemExit(f"unknown upstream data, not built: {e}")
    packed = trave.gzip_bytes(data)
    tmp = out.with_name(out.name + ".part")
    tmp.write_bytes(packed)
    os.replace(tmp, out)
    print(f"built {out}: {len(packed):,} bytes ({len(data):,} unpacked)", flush=True)
    if a.check:
        check(out, fribb, anime_lists)


if __name__ == "__main__":
    sys.exit(main())

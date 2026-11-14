# anime-mappings

Two community anime mapping datasets in one gzipped file, rebuilt every day they change:

- **[Fribb/anime-lists](https://github.com/Fribb/anime-lists)**' `anime-list-mini.json`: which AniDB, MyAnimeList,
  Kitsu, AniList, aniSearch, AnimeCountdown, Simkl, Anime News Network and LiveChart entry is which TMDB, IMDb and
  TheTVDB title, season and episode offset (about 40,000 rows).
- **[Anime-Lists/anime-lists](https://github.com/Anime-Lists/anime-lists)**' `anime-list.xml`: where each AniDB
  entry's episodes lie on TheTVDB's and TMDB's seasons, with its name and supplemental info (about 11,000 entries).

`anime-mappings.bin.gz` holds everything both files carry but Fribb's Anime-Planet IDs, losslessly, as a
[Trave file](#the-format): tables of named, typed columns that an app reads with nothing but a gzip decoder. It is
about 0.65 MB (1.5 MB unpacked), against 6 MB and 1.7 MB for the two files as published (1.5 MB gzipped).

The dataset leaves out Fribb's `anime-planet_id` (Anime-Planet's string slugs): they were a third of the file
(0.95 MB with them). Fribb's own files have them.

## The data is Fribb's and Anime-Lists'

Every value in the file comes from those two projects, unchanged. Credit them, not this repository:

- Fribb's anime-lists, https://github.com/Fribb/anime-lists, by Fribb and its contributors.
- Anime-Lists' anime-lists, https://github.com/Anime-Lists/anime-lists, by its maintainers and contributors.

Neither project publishes a licence. Report mapping errors to them, not here.

Each release's notes name the exact commit of each upstream repository it was built from
(`Fribb/anime-lists@<sha>`, `Anime-Lists/anime-lists@<sha>`), with links to the two files at those commits.

The code in this repository (the builder, the workflow) is under the [MIT licence](LICENSE); the licence covers the
code, not the data.

## Releases

A [workflow](.github/workflows/release.yml) runs every day and on demand. It reads both upstreams' current commits
(their default branches), stops when the latest release was built from the same two with the same `build.py` and
`requirements.txt` (its notes name both blobs), and otherwise downloads both files at those commits, builds the file,
reads it back and compares it field by field with both files (`build.py --check`), and publishes a release tagged
`vYYYY.MM.DD` (`vYYYY.MM.DD.2`, `.3`, ... for a second release the same day, UTC) with two assets:

| Asset | Contents |
|---|---|
| `anime-mappings.bin.gz` | the Trave file, gzip |
| `SHA256SUMS` | its SHA-256, as `sha256sum` writes it |

The latest one is always at:

```sh
curl -LO https://github.com/edde746/anime-mappings/releases/latest/download/anime-mappings.bin.gz
curl -LO https://github.com/edde746/anime-mappings/releases/latest/download/SHA256SUMS
sha256sum -c SHA256SUMS
```

The builder knows every key, attribute and element of both files, and leaves out only the keys it lists as dropped
(`FRIBB_DROPPED`: `anime-planet_id`); `--check` compares every other field. Anything else (a new key, a new element,
a value of another type) stops the build with the reason, so new upstream data stops the release until the builder
knows it, instead of being dropped. The same two files always give the same bytes (`gzip -9`, no file name, no time).

## Building

```sh
python -m pip install -r requirements.txt
python build.py anime-list-mini.json anime-list.xml anime-mappings.bin.gz --check
python build.py --dump anime-mappings.bin.gz       # its tables and columns, with their sizes
```

Python 3.9 or newer, plus `trave` (`pip install -r requirements.txt`). `build.py` reads the file back with
`trave.read`; its `fribb_rows` turns the Fribb table back into the JSON's rows, `anime_lists_tree` the three
Anime-Lists tables back into the XML's elements.

## The format

The file is a [Trave](https://github.com/edde746/trave) file (the README there is the spec), one gzip member, with
the magic `AMAP`. Apps read it with any Trave library (Python `trave`, Go `github.com/edde746/trave/go`, Kotlin
`dev.edde746:trave`, Dart `trave`), or with nothing but a gzip decoder by following the spec. A reader finds the
tables and columns below by name; new columns and tables may appear in later files, and their order may change.

### `fribb`

One row per element of `anime-list-mini.json`, in the file's order. A column holds a key's value; a dotted name holds a
key of an object: `season.tvdb` is `{"season": {"tvdb": …}}`. A row's JSON object is its present values (key order
isn't kept), without `anime-planet_id`, which the dataset leaves out.

| Column | Type | JSON |
|---|---|---|
| `type` | dict | `type`: `TV`, `MOVIE`, `OVA`, `ONA`, `SPECIAL`, `UNKNOWN` |
| `anidb_id` | int_delta | `anidb_id` |
| `mal_id` | int_delta | `mal_id` |
| `kitsu_id` | int_delta | `kitsu_id` |
| `anisearch_id` | int_delta | `anisearch_id` |
| `anilist_id` | int_delta | `anilist_id` |
| `animecountdown_id` | int_delta | `animecountdown_id` |
| `simkl_id` | int_delta | `simkl_id` |
| `animenewsnetwork_id` | int_delta | `animenewsnetwork_id` |
| `livechart_id` | int_delta | `livechart_id` |
| `themoviedb_id.tv` | int | `themoviedb_id: {"tv": id}`, a series |
| `themoviedb_id.movie` | int_list | `themoviedb_id: {"movie": [ids]}`, films |
| `imdb_id` | str_list | `imdb_id: ["tt…"]`, as written (an empty string included) |
| `tvdb_id` | int | `tvdb_id`, a TheTVDB series |
| `season.tvdb`, `season.tmdb` | int | the season of `tvdb_id`, `themoviedb_id.tv` |
| `episode_offset.tvdb`, `episode_offset.tmdb` | int | episodes of that season before this entry's first |

### `anime_lists`

One row per `<anime>` of `anime-list.xml`, in the file's order; `anidbid` is unique and links the rows to `fribb`'s
`anidb_id` and to the next two tables. Attributes are as written, except that a number is stored as one:

| Column | Type | XML |
|---|---|---|
| `anidbid` | int_delta | `anidbid` |
| `tvdbid` | int | `tvdbid` when it is a decimal number |
| `tvdbid_text` | dict | `tvdbid` when it is anything else: `movie`, `OVA`, `hentai`, `web`, ... |
| `defaulttvdbseason` | int | `defaulttvdbseason` when a number |
| `defaulttvdbseason_text` | dict | `defaulttvdbseason` otherwise: `a`, absolute numbering |
| `episodeoffset` | int | `episodeoffset` |
| `tmdbtv` | int | `tmdbtv`, a TMDB series |
| `tmdbseason` | int | `tmdbseason` when a number |
| `tmdbseason_text` | dict | `tmdbseason` otherwise: `a` |
| `tmdboffset` | int | `tmdboffset` |
| `tmdbid` | int_list | `tmdbid`, TMDB films, comma-separated in the XML |
| `imdbid` | str_list | `imdbid`, comma-separated in the XML |
| `name` | str | `<name>`'s text |
| `before` | str | `<before>`'s text |

A decimal number is `-?(0|[1-9][0-9]*)`, so the attribute's text is the number written out again; `tmdbid`'s and
`imdbid`'s text is the list joined with `,`.

### `anime_lists_mappings`

One row per `<mapping>` (in `<mapping-list>`), in the file's order: an entry's mappings are consecutive rows.

| Column | Type | XML |
|---|---|---|
| `anidbid` | int_delta | the `<anime>`'s `anidbid` |
| `anidbseason`, `tvdbseason`, `tmdbseason`, `start`, `end`, `offset` | int | the attributes of the same names |
| `text` | str | the text, verbatim: `;anidb-tvdb;…;`, `+` between several episodes, `-0` for none |

### `anime_lists_supplemental`

One row per element of a `<supplemental-info>`, in the file's order.

| Column | Type | XML |
|---|---|---|
| `anidbid` | int_delta | the `<anime>`'s `anidbid` |
| `block` | int | which `<supplemental-info>` of that `<anime>` holds it, from 0 |
| `replace` | dict | that `<supplemental-info>`'s `replace` attribute |
| `element` | dict | `studio`, `genre`, `director`, `credits` or `fanart` |
| `text` | str | the element's text; for `fanart`, its `<thumb>`'s |
| `dim`, `colors`, `preview` | dict, dict, str | a `fanart`'s `<thumb>`'s attributes |

An `<anime>`'s elements come in the order `<name>`, `<mapping-list>`, `<before>`, `<supplemental-info>`...; the builder
stops on any other order, on an empty `<mapping-list>` or `<supplemental-info>`, and on a `<fanart>` without exactly one
`<thumb>`, so the tables give back the XML's elements exactly. Layout whitespace between elements isn't kept.

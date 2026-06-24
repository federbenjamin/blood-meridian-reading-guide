# Blood Meridian Reading Guide

## What is this

A chapter-by-chapter vocabulary companion to Cormac McCarthy's *Blood Meridian*. The novel is dense with archaic, dialectal, foreign, and technical words; this guide defines them in reading order, each with the sentence from the book it appears in, so you can follow what's actually being said.

**The reading guide itself is an EPUB — that's the main thing:**

| File | What it is |
|---|---|
| `Blood_Meridian_Vocabulary_Companion.epub` | The reading guide. ~1,500 terms, chapter by chapter, each with a definition and the book quote it comes from. Opens in any e-reader (Kindle, Apple Books, Kobo, etc.). Read it alongside the novel. |

**Bonus for Kindle owners — pop-up lookup dictionaries.** If you read the novel on a Kindle, you can also sideload one of these so that tapping a word brings the definition up in place, without leaving the page. The three `.mobi` files are in [`dictionaries/`](dictionaries):

| File | What it is |
|---|---|
| `Blood_Meridian_Dictionary_Extended.mobi` | **Recommended.** A full English dictionary (Webster's 1913, ~102,000 words) with this book's ~1,300 special terms folded in. For those terms the popup shows the in-context gloss and book quote first, then a general definition below. |
| `Webster_1913_Dictionary.mobi` | The general dictionary alone (Webster's 1913), no Blood Meridian additions. A good all-purpose lookup dictionary for any book. |
| `Blood_Meridian_Dictionary.mobi` | Only the ~1,300 Blood Meridian terms, nothing else. Small and focused. |

## How to use it

### The reading guide (EPUB) — start here

It's an ordinary ebook; read it next to the novel.

- **Kindle:** copy `Blood_Meridian_Vocabulary_Companion.epub` into the Kindle's `documents` folder over USB, or email it with [Send to Kindle](https://www.amazon.com/sendtokindle). It shows up in your library as a book to open.
- **Apple Books / Kobo / Google Play Books / any reader app:** just open the `.epub`.

### Bonus: the pop-up dictionaries (Kindle only)

Sideloading over USB is the reliable way (Send-to-Kindle often won't register a file as a *dictionary*):

1. Connect your Kindle with a USB cable. It shows up as a drive.
2. Copy the `.mobi` you want (recommended: the Extended one) into the **`documents`** folder.
3. Eject the Kindle and unplug it.
4. On the Kindle: **Settings → Languages & Dictionaries → Dictionaries**. Under **English**, set the new dictionary as the default — or leave the default and switch per-book: long-press a word in the novel and tap the dictionary name at the top of the popup.

Then long-press any word while reading and the definition appears.

## Building the dictionaries from source

The dictionaries are generated from the reading guide plus the public-domain Webster's 1913 word list:

```
python3 build_dicts.py
```

The script reads the ~1,300 special terms out of `Blood_Meridian_Vocabulary_Companion.epub`, downloads the Webster's 1913 source on first run, and — if it can find Amazon's `kindlegen` — writes `Webster_1913_Dictionary.mobi` and `Blood_Meridian_Dictionary_Extended.mobi` into `dictionaries/`. `kindlegen` is the legacy dictionary builder bundled inside Kindle Previewer on macOS; if it isn't found, the script writes the dictionary source instead so you can build it yourself. Run `python3 build_dicts.py --help` for options.

See [`docs/BUILD.md`](docs/BUILD.md) for the repository layout, build internals, and how to run the tests.

---

*The reading guide was compiled by Benjamin Feder. The general definitions come from Webster's 1913 Dictionary (public domain), via [matthewreagan/WebstersEnglishDictionary](https://github.com/matthewreagan/WebstersEnglishDictionary). Short quotations from* Blood Meridian *are used to illustrate word meanings.*

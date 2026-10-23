%% Deluge Companion manual — English text.
%% The markup is described at the top of delugeapp/ui/manuel.py.
%% The {#…} anchors are shared with the French text: never translate them.

@partie prise-en-main GOLD | Getting started | Installing the application, finding your way around, and your first steps in ten minutes

# Welcome {#bienvenue icone=info}

> Deluge Companion keeps your Synthstrom Deluge company on the computer: it tidies its card, takes care of it, and makes sounds and songs the machine can play.

The Deluge is a self-sufficient machine. But everything it knows — your songs, your presets, your kits, thousands of samples — lives on a small SD card, and the machine does little to help you keep that card in order. A moved sample silently mutes a kit; a duplicated preset can't be spotted on the screen; a backup is always something you think of afterwards.

Deluge Companion is the workshop that was missing next to the machine. It reads the card, shows you what it holds and what state it is in, repairs what is broken, and adds a set of creative tools that write straight into the Deluge's format.

## What the application does {#ce-que-fait}

- **Browse the card**: samples with their waveform, tempo and key; synth presets with their oscillators, filters and modulation; kits row by row; songs clip by clip.
- **Listen** to every sound with one click — computed by the computer, or played by the Deluge itself when it is connected.
- **Look after the card**: twenty-one checks, a score out of 100, guided repairs (missing samples, duplicates, forbidden names, junk files, audio defects) and backups.
- **Create**: synth presets by musical genre, drum kits drawn from your library, chord progressions, rhythms, song structures — and write them **as Deluge songs**, ready to load on the machine.
- **Compose** in the studio: a whole song in a style — sounds, clips and their variations, sections —, played live on the Deluge, written as a new song, or added to one of yours in a new version.
- **Work with the Deluge connected**: its card stays inside and opens over the USB cable, its screen is mirrored on the computer, its tempo drives the tools.

## What it does not do {#ce-quelle-ne-fait-pas}

- It **does not replace the Deluge's sequencer**: you don't compose a song note by note in the application.
- It **never rewrites an existing song**: the format is too rich for a read-and-rewrite to be safe. It creates new ones alongside.
- It **cannot load a preset on the machine remotely**: no MIDI message allows it. The Deluge always plays the instrument selected on it.
- It needs **neither the Internet nor an account**: everything happens on your computer.

## The golden rule {#regle-dor}

!!! retenir Nothing is written without your consent
    A Deluge card holds months of work. The application changes nothing unless asked: every tidy-up, every repair, every deletion is **simulated** first, and the exact plan — file by file — is shown before anything changes. Every rewritten XML file leaves a `.bak` copy next to it. The chapter [The no-destruction rule](#non-destruction) details these safeguards.

## How to read this manual {#lire-ce-manuel}

The manual follows the conventions of the *Deluge Guide*.

| Notation | Meaning |
|---|---|
| [Scan] | a button, check box or tab of the application, exactly as written on screen |
| [[Ctrl+R]] | a key or key combination |
| `SAMPLES/DRUMS` | a folder, a file, or a Deluge word |
| Settings ▸ Deluge card | a path: the page, then the part of the page |
| [Open card health](app:Health) | a link that opens the page in the application |

Five kinds of boxes punctuate the text, as in the guide:

!!! astuce A shortcut, a faster way
    Tips save time; you can do without them.

!!! attention A trap worth knowing
    What may surprise you, or lose work if ignored.

!!! pro A habit that has proved itself
    What seasoned users do, and why.

!!! atelier Step by step
    An exercise to do while reading, with the application open alongside.

This manual opens from **Help ▸ Manual**, or with the [[F1]] key: it then opens straight at the chapter of the page you are looking at. The left column is its table of contents; the search field at the top ignores accents and capitals; the [Français] and [English] buttons switch its language without losing your place; [PDF…] saves it for printing.

# Installation and start-up {#installation icone=settings}

> A few minutes are enough: Python, two libraries, and the application opens — even without a card.

## What you need {#prerequis}

- **Windows**, preferably: that is where the application is developed and where the MIDI link with the Deluge works. It starts elsewhere too, without that link.
- **Python 3.11** or newer.
- Two required libraries: **PyQt6** for the interface and **numpy** for audio.
- One optional library: **sounddevice**, to hear sounds on the computer. Without it everything works, but the listen buttons stay silent.
- For the link with the machine: a USB cable, and the Deluge **community firmware** — version 1.3 or newer for the card to open over the cable.

## Installing {#installer}

In the application folder, a single command installs what is needed:

`pip install -r requirements.txt`

Then the application starts with:

`python main.py`

A splash screen in the guide's colours shows while loading, then the main window opens.

**One window at a time**: launching the application again brings the open window to the front. Two windows would fight over the connected Deluge: each would sync its card, and every reply from the machine would reach both.

## Launch options {#options}

| Option | Effect |
|---|---|
| `--sd PATH` | uses this card for the session, and remembers it |
| `--reset-db` | empties the index before starting; it is rebuilt at the next scan |
| `--no-splash` | no splash screen |
| `--verbose` | detailed log in the console |
| `--version` | prints the version, then quits |

!!! pro Carrying the application on a stick
    The `DELUGE_COMPANION_CONFIG` environment variable moves the folder holding the settings, the index and the log. Pointed at a USB stick, it makes the installation portable, settings included.

## The first start {#premier-demarrage}

The application opens **even without a card**: that is the normal case the first time. If it finds a Deluge card on a connected drive, it offers to use it. Otherwise it opens the Settings page, and the screen in the top bar reads “NO CARD — CLICK TO CHOOSE”.

Every page then shows the same welcome: “Where is your Deluge card?”, and two buttons — [Choose the folder], which leads to the settings, and [Detect the card], which searches the connected drives by itself.

The next chapter presents the window; the chapter [The card and the index](#carte-et-index) explains how to designate your card and have it read.

# Finding your way around {#se-reperer icone=grid}

> The window echoes the Deluge's front panel: a row of glowing pads on the left, a screen at the top, and one colour per page.

[[figure fenetre | The main window and its ten markers, described below. | ]]

| Marker | Element | Role |
|---|---|---|
| 1 | The column of pads | the ten pages; the pad of the page shown lights up |
| 2 | The menus | File, Edit, Tools, Language, Help |
| 3 | The screen | the open card, and every message from the application |
| 4 | The “Deluge” chip | the state of the connected machine; a click acts on it |
| 5 | The search | finds a sample by name, from any page |
| 6 | [Scan] | rereads the card and updates the index |
| 7 | The play key | plays or stops, like [[Space]] |
| 8 | The glowing strip | the colour of the page shown |
| 9 | The page header | its circuit lattice, its title, its actions |
| 10 | The status bar | messages, progress, free space |

## One colour per page {#couleurs}

Just as each part of the guide has its own, each page of the application wears a colour taken from the machine's pads. You find it everywhere: the pad in the column, the strip under the top bar, the header, the main button, selections, tabs, check boxes and sliders.

[[figure pages | The ten pages and their keyboard shortcut. | Dashboard ; Samples ; Presets ; Kits ; Songs ; Generator ; Studio ; Tools ; Health ; Settings]]

The colour also tells **where a shortcut leads**: on the dashboard, the [Back up card] button is orange because it leads to the Health page — and it opens it right on the backups tab.

## The column of pads {#colonne}

A click on a pad opens its page; the number on the right is its shortcut, from [[Ctrl+1]] to [[Ctrl+9]], then [[Ctrl+0]] for the tenth. The [Collapse] button at the bottom shrinks the column to its pads alone, making room for the lists; [[Ctrl+B]] does the same. The same gesture unfolds it again.

## The top bar {#barre-du-haut}

**The menus** gather the general commands:

| Menu | What it holds |
|---|---|
| File | choose the card [[Ctrl+O]], scan it [[Ctrl+R]], back it up, send files [[Ctrl+I]] or a folder [[Ctrl+Shift+I]] to the Deluge, quit [[Ctrl+Q]] |
| Edit | search [[Ctrl+F]], the settings [[Ctrl+,]] |
| Tools | the generator [[Ctrl+G]], the toolbox, card health, Deluge Live [[Ctrl+D]], sync with the Deluge [[Ctrl+Shift+D]], collapse the column [[Ctrl+B]] |
| Language | Français or English |
| Help | this manual [[F1]], the first steps, keyboard shortcuts, about |

**The screen** is the Deluge's own. In large type, the name of the open card; in small type, what it holds or what is waiting for it. Every message from the application shows there for a few seconds — scrolling if too long, as on the machine. A click on the screen opens the card settings.

[[figure ecrans | Three states of the screen: the Deluge's card, the backup, no card. | WORKING COPY · 3 TO SEND ; DELUGE CARD ; you are working on the copy kept in step with the card, three files are waiting for the Deluge ; BACKUP · READ-ONLY ; SDCARD DELUGE ; the backup is open, nothing will be written to it ; NO CARD ; CLICK TO CHOOSE ; a click leads to the card settings]]

**The “Deluge” chip** tells where the machine stands. It only appears if the computer can speak MIDI.

[[figure pastille | The three states of the chip. | Grey ; no Deluge at the end of the cable ; Gold ; the Deluge is plugged in, a click connects it ; Green ; connected, a click opens Deluge Live]]

**The search** — “Search everywhere…” — looks for a **sample** by name: it opens the Samples page and filters its list. [[Ctrl+F]] puts the cursor there.

**[Scan]** rereads the card (see [Scanning and the index](#analyse)). It stays off while no card is set. Its colour is the front panel's, adjustable in Settings ▸ Appearance.

**The play key**, the round one, stops the current sound or starts the page's listening again. It glows green during playback. [[Space]] does the same.

## The page header and its actions {#en-tete}

Each page opens on a header in its colour: a lit pad, the title in capitals, a sentence saying what the page is for, and the guide's circuit lattice. Below, the **action bar** carries the page's buttons. The **main** button — only one per screen — is solid and glowing.

!!! retenir A greyed-out button is waiting for something
    Most of the time, a row picked in the list. [Slice…], for instance, only lights up when a single sample is selected, since slicing works on one loop at a time.

In a narrow window, the bar's buttons fold down to their icon rather than cutting their name. Leave the mouse over one: the tooltip gives its name.

## Every command explains itself {#infobulles}

Leave the mouse for a second over any button, check box, list or slider: a tooltip says **what will happen** — not its name, which you can already read. Most commands that write to the card say so up front, in bold: “**Writes to the card.**” — you know before clicking. The chapter [The no-destruction rule](#ce-qui-ecrit) gathers them all.

## The status bar {#barre-etat}

At the bottom of the window: the application's latest message, a progress bar during long work, “● playing” during playback, and the card's free space.

## Long tasks {#travaux-longs}

A scan, a sample treatment, a backup, a sync: anything that takes time runs in the background, and the window stays usable. If you quit during a task, the application asks for confirmation before interrupting it.

## Changing the language {#langue}

The **Language** menu offers “Français” and “English”, each written in its own language. The choice is kept at once, then the application offers to restart — the question is asked in both languages. Declining keeps the choice for the next start.

!!! pro What the application writes takes the current language
    The names it gives to what it writes — clips of a song, tracks of a MIDI file, folders of a tidy-up — follow the interface language at the moment of writing: “Accords” in French, “Chords” in English. What is already on the card does not change.

# The card and the index {#carte-et-index icone=save}

> The application never works blind: it reads your card once, keeps an index of it, and every page relies on that index.

## Three ways to open the card {#trois-facons}

| Situation | Where to set it | What the application does |
|---|---|---|
| The card stays in the Deluge, connected over USB (firmware 1.3 or newer) | Settings ▸ Deluge card | it works on a **working copy** kept in step with the card |
| The card sits in a reader on the PC | Settings ▸ Other card location | it works directly on the card |
| A folder: a copy of the card, a backup | Settings ▸ Other card location | it works there; the declared **backup** opens read-only |

The first way is the most comfortable: the card never leaves the machine. It has its own chapter, [The card stays in the Deluge](#carte-dans-le-deluge).

## Designating the card {#designer}

In Settings ▸ Other card location, type the path to the card's **root** — the folder that contains `SONGS`, `SYNTHS`, `KITS` and `SAMPLES` — or look for it with [Browse…]. The field checks what you type as you type: “Deluge folder tree recognised”, with the free space, or what is missing. [Use this card] adopts it.

[Detect cards], at the top of the page, searches every connected drive: any location holding **at least two** of the `SONGS`, `SYNTHS`, `KITS` and `SAMPLES` folders is recognised as a Deluge card. Each card found becomes a button. **Recent paths** stay available in a list. The File ▸ Choose card… menu [[Ctrl+O]] opens a folder picker directly.

## Scanning and the index {#analyse}

Once a card is set, it has to be **read**: [Scan] in the top bar, or [[Ctrl+R]]. The scan goes through the card and fills the **index** — a small database kept on the computer, not on the card — with what it finds: every sample, preset, kit and song, and what links them together.

- The scan **changes nothing** on the card: it only reads.
- It is **incremental**: the second time, only changed files are reread. A card of 1,700 samples takes a few minutes the first time, then a few seconds.
- It **stops** without harm: [Stop], on the dashboard, keeps what has already been read.
- At start-up, the application rereads by itself what has changed since last time (a fraction of a second): the [Update the index at start-up] box in the settings.

Two options, in Settings ▸ Card scanning, decide what the scan measures:

| Option | By default | What it brings | Its cost |
|---|---|---|---|
| [Compute fingerprints (duplicate detection)] | on | duplicates are recognised by their content, not their name | almost nothing: three small blocks read per file |
| [Acoustic analysis (tempo, key, levels)] | off | tempo, key and levels of every sound: similarity search, harmonic mixing, the clipping and DC checks | clearly slower: one more minute for 1,700 sounds, the first time |

!!! astuce Turn acoustic analysis on once
    It lengthens the first reading, then later scans only reread what has changed. It is what powers “Similar sounds”, the search by key and half of the audio health checks.

## When to scan again {#quand-analyser}

The application's own writes update the index by themselves, as do files received from the Deluge. Scan again when the card has changed **outside the application**: files copied by hand onto a card in the PC's reader, for instance. When in doubt it costs nothing: what hasn't changed is not reread.

[Reset the index], in the settings, empties the index so it is rebuilt at the next scan. The card is not touched, and your ratings, favourites and tags are kept.

# First steps in ten minutes {#premiers-pas icone=play}

> A guided tour, from setting the card to the first song written for the Deluge.

!!! atelier Your first session
    Keep this manual open next to the application and follow the steps in order. Nothing below changes your card without asking you.

1. **Set the card.** If the application offered a detected card, accept. Otherwise open [Settings](app:Settings) and designate the card's root — or, if your Deluge has firmware 1.3, connect it and create the working copy (see [Creating the working copy](#creer-copie)).
2. **Read it.** Click [Scan], at the top. The status bar shows the progress; the first reading takes a few minutes on a big card.
3. **Look at the dashboard.** The tiles say what the card holds; the ring, its health score. The “Do this now” banner suggests the most useful thing at this moment, with the button that does it.
4. **Back up.** If the banner suggests it, follow it: [Back up] leads to the backups tab of the Health page, where [Back up now] copies your songs, presets and kits in under a second.
5. **Listen to a sound.** Open [Samples](app:Samples), pick a folder in the tree, then a sound in the list: one click plays it. [[Space]] stops.
6. **Make a preset.** Open the [Generator](app:Generator), pick a genre — Techno, for instance — and a role, Bass. [Generate], then [Listen]. Not convinced? [Mutate] varies it, [Make 8 variations] offers eight cousins.
7. **Keep it.** [Save to SYNTHS] asks for a name and a folder, then writes it to the card.
8. **Try it in context.** [Try in a song] writes a new song into `SONGS` where your sound plays a phrase made for its role, over the genre's drums. Load it on the Deluge and press PLAY.
9. **Connect the Deluge.** USB cable, and the “Deluge” chip in the top bar turns gold, then green. The chapter [Connecting the Deluge](#brancher) gives the two settings to make once on the machine.

!!! astuce F1, everywhere
    On any page, [[F1]] opens this manual at the chapter describing it.

@partie pages PAD_YELLOW | The ten pages | One page per area, each in the colour of its pad

# Dashboard {#tableau-de-bord page=Dashboard}

> The state of the card on one screen: what it holds, its health, and the next thing to do.

The dashboard is the home page. It reads from top to bottom: first what needs your attention, then the contents, then the details.

## Do this now {#a-faire}

The top banner gives **only one** suggestion — the most useful at this moment — and the button that carries it out or leads to the exact place. Its pad takes the colour of the page it leads to. The order follows the risk, not the features:

| Situation | Suggestion | Button |
|---|---|---|
| the card has never been read | scan it | [Scan card] |
| no backup of the card | back up, before any fix | [Back up] |
| the backup lacks what the Deluge has recorded | update it | [Update the backup] |
| presets ask for missing samples | find them | [Find them] |
| duplicate files | see them | [See the duplicates] |
| more than 200 unused samples | tidy them up | [Tidy them up] |
| nothing to report | make a sound | [Generate a preset] |

## The Deluge and the PC {#deluge-et-pc}

This panel tells where the link with the machine stands, what is waiting to go to it, and what has come from it. Its pad changes colour:

| Pad | Meaning |
|---|---|
| green | the Deluge is connected, and its card opens over the USB cable |
| gold | the Deluge is connected, but its card doesn't open over USB: firmware 1.3 is needed |
| amber | sync in progress |
| grey | the Deluge is unplugged; or the backup is open, read-only |
| cyan | the card is open directly, in a reader on the PC |

Its commands: [Sync], to exchange with the Deluge right away; [Send files…], to pick sounds or presets on the PC to put on the card; and, when the backup is open, [Deluge card…], which leads to the settings. The **Received from the Deluge** list shows the last six songs, presets, kits or sounds that arrived from the machine: a click opens each one on its page, selected. If your backup is behind the card, a line says so, with [Update the backup].

The dotted frame is a reminder: files dragged anywhere onto the window go to the Deluge (see [Exchanging files](#echanges)).

## Card contents {#contenu}

Six tiles: **Samples**, **Synth presets**, **Kits**, **Songs** — a click opens the matching page —, the total **audio length** of the samples, and the **free space**. On a folder rather than a card, the last tile reads “Free on the disk”: those are the computer disk's figures.

## Card {#carte}

The card's path, a fill gauge, the space used including the samples' share, and the date of the last scan. While the card has never been read, the [Scan card] button shows here; during a scan, [Stop] interrupts it without losing what has been read.

## Health {#etat-sante}

The health score in its ring, the overall verdict, and the three most serious problems. **Each problem is a link**: a click leads to the Health tab that repairs it. [See the details] opens the full diagnosis. While the card hasn't been scanned, no score is shown: announcing a card in good shape without having read it would be a lie.

## Quick actions {#actions-rapides}

Six shortcuts, each in the colour of its destination, leading **to the exact tab**: [Generate a preset], [Build a kit], [Find duplicates], [Missing samples], [Back up card] and [Toolbox].

## Where the samples are {#repartition}

The ten folders holding the most samples, grouped at the second level (`SAMPLES/DRUMS` rather than each of its subfolders), each with a row of pads that reads like a level meter on the machine.

# Samples {#echantillons page=Samples}

> The whole sound library: browse, listen, filter, process, slice, and find a sound by similarity.

[[figure echantillons | The layout of the Samples page. | Actions ; listen, process, slice, similar sounds, send ; Filters ; search, category, length, unused, favourites, missing ; Folders ; the card's tree, a click filters the list ; The list ; a click selects, dragging to the PC copies ; The preview ; waveform, format, rating, favourite, uses]]

## The list {#liste-echantillons}

Each row is a sample on the card. The columns, in order of importance — in a narrow window, the last ones fade away:

| Column | Contents |
|---|---|
| Name | the file name |
| Folder | the last folder of the path (“Kick” rather than the whole path) |
| Category | deduced from the folder; a coloured dot marks it |
| Length | the sound's duration |
| Key | detected by the acoustic analysis |
| Format | **empty when all is normal** (44.1 kHz, 16 bits, mono); otherwise what is out of the ordinary: “48 k”, “24 b”, “stereo” |
| Size | the file's weight |
| Uses | how many presets, kits or songs use it |

A click on a header sorts the column. A click on a row selects the sound and shows it in the preview; [[Ctrl]] or [[Shift]] select several. The count of sounds shown is written under the list.

## Searching and filtering {#filtres}

- The “Search for a sample…” field filters by name; the search starts by itself after a short pause.
- [All categories] keeps only one category; each says how many sounds it holds.
- [All lengths] isolates sounds by length: very short (under half a second), short, medium, long (over ten seconds).
- [Unused] shows only sounds that no preset, kit or song refers to.
- [Favourites] shows only sounds marked as favourites.
- [Missing] shows only files a preset asks for but that are missing from the card.

## The folder tree {#arbre}

On the left, the sample folder tree, with the number of sounds in each folder. A click on a folder limits the list to its contents; the chosen folder is also where sounds you send to the Deluge from this page will go.

## The preview {#apercu}

At the bottom: the sound's name and path, its **waveform**, and a sheet — length, full format, size, and, if the acoustic analysis has run, tempo, key and category. On the right:

- the **Rating**, from one to five stars;
- the [Favourite] box, used by the [Favourites] filter;
- its **tags**, if it has any — a tag's cross removes it;
- how many files on the card use it.

!!! retenir Ratings and favourites stay on the computer
    They are kept in the application's index, not on the card: the Deluge doesn't see them, and resetting the index keeps them.

## Listening {#ecouter-echantillon}

[Listen] plays the selected sound; [Stop] cuts it. By default, **a single click in the list** is enough to listen: the [Play the selected sample automatically] box, in Settings ▸ Listening, decides. [[Space]] stops or restarts listening from anywhere, and a click on the waveform plays the sound again from the start. The listening volume is set in the settings; it has no effect on the Deluge.

[Show in Explorer] opens the sound's folder in Windows Explorer, changing nothing.

## Process… {#traiter}

[Process…] applies one or more treatments to **every selected sound**. A window offers:

| Treatment | Effect |
|---|---|
| [Mix down to mono] | a single channel: the size is halved, the length doesn't change |
| [Remove DC offset] | re-centres the waveform on zero |
| [Normalise peak to] | raises or lowers the level so the peak reaches the chosen value (−1 dBFS by default) |
| [Trim silence below] | removes silence at the start and end, below the chosen threshold (−60 dB by default) |
| [Fade in and out of] | short fades, to avoid clicks (5 ms by default) |
| [Resample to] | converts to 44,100, 48,000, 32,000 or 22,050 Hz |

[Preview] processes nothing: it computes the **plan**, file by file, and shows it. Nothing is written before you accept it. The treatment then runs in the background.

!!! attention What changes a sound's length
    Resampling and trimming silence change the length of files. Presets that bound this sound in sample frames are **readjusted in the same operation**. But a song is never rewritten: sounds used by a song are therefore **left out** of these two treatments, and the plan says why.

The originals are set aside in the `_BACKUP` folder at the root of the card, byte for byte. On the working copy, this folder stays on the computer and doesn't go to the Deluge.

!!! pro Clipping can't be repaired
    Lowering the level of a clipped sound gives back headroom for mixing; the peaks shaved off at recording time don't come back.

## Slice… {#decouper}

A break, a drum loop, a phrase: [Slice…] turns it into a **kit where each pad plays one slice**. Select **a single** sound, then click.

[[figure boucle | A sliced loop: the cuts on the waveform, one pad per slice. | the cuts, placed on the transients ; one pad per slice, on the same file ; No audio file is duplicated: each row of the kit plays a portion of the loop.]]

The window shows the waveform with its numbered cuts, and sets how they are placed:

- [On the transients] places the cuts where the sound hits. The **Sensitivity** slider finds more or fewer; the [Snap to tempo] box brings the cuts back onto the grid, so a replayed break stays in time.
- [In equal divisions] cuts into equal parts — enough for a well-trimmed loop: four seconds at 120 BPM give sixteen slices of a sixteenth note.
- **Slices** sets their number, up to 32 (16 by default).

The table gives each slice's start, length and frame count. A click on a row, or on the waveform, **plays the slice**; [Listen] plays it again.

Three ways to finish:

- [Write the kit] writes a kit into `KITS`: each row plays its portion of the **same file**. Nothing is duplicated, and nothing takes more space.
- [Export as files…] writes each slice to its own file, in a `SAMPLES/… TRANCHES` folder. It isn't needed to play the slicing on the Deluge, and it doubles the space used: the window says so before writing.
- [Write as a song] writes a new song into `SONGS`: the slices' kit, and a clip that replays the loop slice by slice, each in its place.

[Close] leaves without writing anything.

## Similar sounds {#sons-proches}

Across thousands of samples, name and folder are no longer enough. Select a sound, click [Similar sounds]: the list now only shows what **resembles** it, from closest to furthest, with a **Closeness** column in percent. The button becomes [Full list], which brings back the whole list.

The comparison uses eight measurements taken by the acoustic analysis: brightness, low and high content, spectral spread, noisiness, peak-to-average ratio, attack time. Neighbours often come from another folder, and that is intended: a kick finds toms, a snare finds rimshots. It is what sounds alike to the ear, not what is filed together.

!!! attention Acoustic analysis is required
    A sound without acoustic measurements can't be compared: the application says so. Tick “Acoustic analysis” in the settings, then scan again.

## From the PC to the Deluge, and back {#envoyer-depuis-echantillons}

[Send to the Deluge…] picks files on the computer and puts them on the card, **in the folder chosen in the tree**. The plan is shown before anything is copied (see [Exchanging files](#echanges)).

The other way round, **drag rows from the list** to Explorer or to your music software: they receive a copy. The card is not touched.

# Presets {#presets page=Synths}

> The card's synth presets: browse them, listen to them, and understand what makes their sound.

## The list {#liste-presets}

Each row is a preset from the `SYNTHS` folder: its **name**, its **folder**, its **category** (deduced from its folder and contents, with its coloured dot), its synthesis **engine** and its **size**. The “Search for a preset…” field filters by name, [All categories] by category. The count is written under the list.

## Overview {#vue-ensemble}

The first tab of the right-hand panel describes the selected preset:

- a one-sentence **description**, then a sheet: engine, polyphony, both oscillators, the filter, the effects, unison, the arpeggiator, the guessed category, the character of the sound, the firmware version that wrote it — and, if there were any, the **repairs made while reading** a damaged file;
- the **waveform** of the sample picked in the “Samples used” list;
- the sound's **spectrum**, which appears after listening;
- **Samples used**: every file the preset reads, and whether it is present — “yes”, or “MISSING” in red.

## Parameters and Modulation {#parametres}

[Parameters] shows the main settings as knobs, from 0 to 50 as on the Deluge's screen (pan from −25 to +25): volume, filter cutoff and resonance, the two oscillator levels, reverb, delay, modulation effect. Below, the two **envelopes** and the **filter curve**. These knobs are for reading; they don't turn.

[Modulation] lists the **patch cables** — source, destination, depth — and the preset's **assigned knobs** (its `modKnobs`).

## Listening to a preset {#ecouter-preset}

[Listen] plays the preset. The computer computes an **approximation** of the sound with its own engine: faithful in spirit, not in every detail. If the Deluge is connected and the “Play presets on the Deluge” box is ticked in the settings, **the machine** plays: the instrument selected on it takes the preset's filters, envelopes and effects, with its own oscillators (see [Listening on the machine](#ecouter-sur-la-machine)). [Stop] cuts it.

## Duplicating, varying {#dupliquer}

- [Duplicate] saves a copy of the preset **next to the original**, under the name “… copy”, after confirmation. The original is not touched.
- [Vary in the generator] opens the preset in the [Generator](app:Generator) as a starting point: [Mutate] or [Make 8 variations] draw cousins from it. The original is never rewritten.

# Kits {#kits page=Kits}

> Drum kits row by row: what each pad plays, and above all what no longer plays.

## The list and the details {#liste-kits}

On the left, the card's kits: name, folder, number of rows, size; the “Search for a kit…” field filters by name. On the right, the selected kit: a sentence sums up its state — “16 row(s), all playable”, or how many have no playable sample.

The **Rows** table gives, for each row: its name, its sample, whether it is **present** (“yes”, “MISSING”, or “empty” for a row with no sound), its volume, its decay and its polyphony.

!!! retenir The Deluge gives no warning
    A row whose sample has disappeared stays silent on the machine, without a message. This is where you see it — and the [Health](app:Health#Manquants) page knows how to find it a replacement.

## Listening {#ecouter-kit}

- [Play the row] plays the sample of the selected row. With automatic listening, a click on the row is enough.
- [Play the kit] plays the **test pattern** with the kit's sounds, at 128 BPM. If the Deluge is connected and listening is set to it, the pattern goes **to the machine**: its rows answer from note 36 (C1) upwards.
- [Stop] cuts it.

## The test pattern {#motif-essai}

Under the table, a step grid: one line per row, sixteen steps per bar. [Starting pattern] loads a genre's typical rhythm into it, **limited to the rows the kit has** (KICK, SNARE, HAT…). Click the pads to add or remove hits. A melodic kit, with no drum names, starts from an empty grid on its first rows: the page says so.

- [Pattern as MIDI] writes the pattern to a `.mid` file, wherever you choose, off the card.
- [Pattern as a song] writes a new song into `SONGS`: this kit, as it is on the card, and a clip playing the pattern (see [Writing songs for the Deluge](#morceaux-pour-le-deluge)).

# Songs {#morceaux page=Songs}

> What each song holds, what it depends on, and what it is missing — read-only.

!!! retenir A page that never changes a song
    A preset can be regenerated, a sample downloaded again; a song is work. Nothing on this page writes to a song file. Its exports write **elsewhere**, wherever you choose.

## The list and the sheet {#liste-morceaux}

On the left, the songs: name, tempo, number of clips, notes, bars; the “Search for a song…” field filters by name. On the right, the selected song: a **thumbnail** in colour, the one from the machine's Song view, and a sheet — tempo, scale, session and arrangement clips, notes, longest clip, sections, instruments, density in notes per bar, swing, firmware.

## Clips, Instruments, Samples {#onglets-morceaux}

| Tab | What it lists |
|---|---|
| [Clips] | each clip: its name, its preset, its length in bars, its number of notes, its section |
| [Instruments] | each instrument — synth, kit, MIDI, CV, audio —, its name, its folder, and whether it is **present** on the card |
| [Samples] | each audio file the song depends on, and whether it is present |

A preset or sample marked “MISSING” will leave the song silent in places on the machine.

## Exporting {#exporter-morceau}

- [Clip as MIDI] writes the clip selected in the Clips tab to a `.mid` file.
- [Song as MIDI] writes the whole song to a single MIDI file, **one track per clip**, drums on the percussion channel. All tracks start at the beginning: the Deluge's clips are loops of the session grid, and the file can't know when each one is launched.
- [Collect…] copies into a folder of your choice the song, **the presets it names and the samples they read**, with their original folder tree. The resulting folder is shaped like a card: copied to the root of another, the song plays there as is. The full list is shown before the first copy, and anything missing is reported.
- [HTML report] saves a sheet of the song as a web page: figures, clips, instruments, missing samples.
- [Show in Explorer] opens the song's folder.

!!! pro Archiving a finished song
    [Collect…] is the right way to put a song in a safe place or to give it away: nothing is forgotten, not even the sample filed elsewhere that a preset asks for.

# Generator {#generateur page=Generator}

> Make synth presets and drum kits, by musical genre or at random, listen to them, then keep the ones you like.

[[figure generateur | The layout of the “Synth preset” tab. | Actions ; generate, random, mutate, listen, save ; Settings ; genre, role, engine, seed, six sliders ; The sound ; description, waveform, spectrum, settings ; Variations ; eight variations, the history, the morph]]

The page has two tabs: [Synth preset] and [Drum kit].

## Choosing a genre and a role {#genre-role}

On the left, **twenty-two genres**, each a pad in its colour: Acid, Ambient, Berlin school, Boards of Canada, Deep house, Detroit, Downtempo, Drum and bass, Dubstep, Electro, Funk, Hardcore, House, IDM, Industrial, Jungle, Lo-fi, Minimal, Psytrance, Synthwave, Techno, Trance. Each one's tooltip describes its character and tempo range.

Below:

- **Role** — what the sound must do in a song: Bass, Lead, Pad, Pluck, Keys, Stab, FX, Drone, Arpeggio, Bell. A bass isn't set up like a pad.
- **Engine** — [Chosen by the genre], which gives the most characteristic sounds, or Subtractive, FM, Ring mod.
- **Seed** — the number that makes a sound reproducible: two generations with the same seed and the same settings give **exactly** the same sound. The die draws a new one.

**Six sliders** steer the result: **Brightness** (the filter), **Movement** (LFOs and modulation envelope), **Space** (reverb and delay), **Dirt** (distortion, resonance, bit reduction), **Width** (unison, detune, chorus) and **Complexity** (the number of modulations).

## Generating and listening {#generer}

- [Generate] makes a complete preset from the genre, role, sliders and seed. Nothing is written to the card yet.
- [Random] draws a genre, a role and a seed, then generates.
- [Mutate] starts from the current sound and changes a few settings: a way to explore around an idea you like.
- [Listen] plays the sound — computed by the computer, or by the Deluge if it is connected and listening is set to it.
- [Edit the sound…] opens the editor of the current sound: each setting by hand, at the machine's step and in plain terms (see [Editing a sound by hand](#atelier-modifier-son)). The edited sound joins the history.

In the middle, the resulting sound: its name and description, its waveform and spectrum, its **resulting settings** as knobs, its amplitude envelope and filter curve.

!!! retenir A generated preset makes a sound
    A silent oscillator, a closed filter, an envelope with neither attack nor sustain are caught before writing.

!!! retenir Listening on the computer follows the Deluge's laws
    Envelope times, filter cutoffs, LFO rates, levels, glide and modulations are computed as in the machine's firmware: a decay of 13 lasts 1.8 seconds here as on the Deluge. The exact timbre of the filter and the effects remains approximate; to hear it exactly, try the sound on the machine with [Try in a song].

## Variations, history, morph {#variations}

On the right:

- [Make 8 variations] creates eight cousins of the current sound. **One click** on a variation plays it, **a double-click** adopts it.
- **History**: every generated sound piles up there; a double-click brings it back.
- **Morph**: pick a sound in the history, set the slider — the current sound on the left, the chosen sound on the right — then click [Morph]. Continuous settings blend according to the amount; clear-cut choices, like waveforms, switch over halfway.
- [Generate a batch into a folder…] makes up to 64 presets of the chosen genre at once and writes them into a subfolder of `SYNTHS`.

## Keeping a sound {#enregistrer-preset}

[Save to SYNTHS] asks for a **name** — cleaned up for the card — then a **subfolder** of `SYNTHS` (“Generated” by default; empty for the root of `SYNTHS`). If a file already has that name, the application asks before replacing it — and, with the settings' safeguard, keeps a `.bak` copy of the old one.

[Try in a song] writes a new song into `SONGS` where the sound plays a phrase made for its role — bass, chords, arpeggio, melody — over a progression and the genre's drums: a way to hear it **in context** on the machine.

## Building a kit {#construire-kit}

The [Drum kit] tab assembles a kit **from your samples**. The kit is built around a machine or a bank from your library — a 909, a Linndrum, an artist kit —, chosen according to the genre; roles it lacks are filled in from elsewhere. Each row is set up the way the Deluge creates one: the sample played to the end and velocity-sensitive; volume and pan follow the kits on the card, toms fanned out.

- **Genre** steers the choice of sounds: a techno kick doesn't sound like a funk kick.
- **Kit name** is the name of the file written into `KITS`.
- **Seed**: same seed, same kit.
- **Preferred folder**, optional, limits the search to one folder of the card, for instance `SAMPLES/Artists/…`.

[Build the kit] assembles it — nothing is written yet. [Listen] plays it. Don't like a row? Pick it in the list, then [Another sound]: another sound of the same role replaces it, from the same machine first, then from a neighbouring one. [Save to KITS] writes it into `KITS` under the kit's name; if the name is already taken, the application asks before replacing the file. [Kit as a song] writes a new song: this kit and a clip playing its genre's rhythm.

!!! attention The kit draws on the index
    Without a scan of the card, the kit builder finds no samples. Run [Scan] first.

# Studio {#atelier page=Atelier}

> Composing a song from the first sound to the arrangement: a style, sounds, clips and their variations, sections — then writing it for the Deluge, or completing a song started on the machine.

[[figure atelier | The four tabs of the studio, the section grid, and the three routes to the Deluge. | Style ; the genre, the key, the tempo, the character of the sounds and the parts ; Sounds ; one sound per track, and eight variations in the style ; Clips ; clips and their variations, on the song's progression ; Song ; the sections, and the clip each track plays in them ; The section grid ; one row per track, one column per section, one letter per clip — an unlit cell is silent ; Play on the Deluge ; live, in the clip MIDI Follow is following, locked to its bar ; Write the song ; a new song in SONGS, sections and arrangement included ; Complete the song ; a new version of yours, the original intact]]

The page follows the order of the work, in four tabs: Style, Sounds, Clips and Song. The four buttons of the header drive it: [Compose] makes a new song, [Start from a song…] opens one of yours, [Write the song] and [Complete the song] write it to the card. Until then, **nothing is written**: the studio composes even without a card, and only asks for it to write, or to build a kit from your samples.

## The style {#atelier-style}

On the left, the generator's twenty-two **genres**, one pad each; the tooltip describes the genre's character and its tempo range. Choosing one puts the tempo in the middle of that range.

- **Root** and **Scale** — chords, bass and melody stay in the scale; the written song gives it to the Deluge's scale mode.
- **Tempo**, in BPM.
- **Mood** — the mood of the chord progression: melancholic, house, jazz… By default, the genre's.
- **Colour** — triads, sevenths, ninths or suspended chords. By default, what the mood calls for.
- **Seed** — same seed and same settings, same song; the die draws a new one.

**Character of the sounds** takes up the generator's six sliders — Brightness, Movement, Space, Dirt, Width, Complexity —, but for **every** synth of the song at once: that is what makes them sound together.

**The tracks** says which parts the song contains: [Drums], [Bass], [Chords], [Arpeggio], [Melody]. For each one, the list beside it says where it plays:

| Kind | Where the part plays |
|---|---|
| Kit | a Deluge kit, built from your samples — these are the drums |
| Synth | a Deluge synth, whose sound is generated in the style |
| MIDI | an external device, which the Deluge drives on the chosen channel (1 to 16) |
| CV | a modular synth, through the chosen CV output (1 or 2) — one note at a time |

[Compose] then makes the project: one track per ticked part, a sound in the style for each, a first clip, and the **genre's structure** — intro, build-up, theme, breakdown… — with the variations it calls for: lighter drums for the intro, no kick for the breakdown, ornamented for the peak; at the second peak, the melody answers the first one and the bass grows richer.

## The sounds {#atelier-sons}

On the left, the project's tracks, each in the colour of its part; on the right, the sound of the chosen track, its name and its description.

- [Play the sound] plays it — on the Deluge if listening is set to it, otherwise as an approximate render; drums play their first clip.
- [Another sound] draws another one in the same style for a synth; for drums, another kit built from your library.
- [Choose on the card…] takes a preset or a kit from the card for the track, chosen in the index.
- A MIDI or CV track shows its **channel**, which can be changed here.

**Variations in the style**: [Suggest 8 variations] offers eight of the track's sound. Each one touches **a single** facet: either a facet drawn again — the timbre, the filter, the envelopes, the movement, the space, the width, the modulations —, or a slider pushed — brighter, darker, dirtier, wider, more space… The rest of the sound does not move, and nothing leaves the genre. A click plays a variation; a double-click, or [Adopt], gives it to the track.

!!! retenir Dirtier means the same sound, dirtier
    Each decision of the sound — the cutoff, the drive, the shape of the LFOs — has its own random draw. Pushing the dirt therefore only changes what depends on it: you get the same sound, dirtier, and not another sound.

Under the list, two menus and two buttons add or remove a track: the **kind** of track (kit, synth, MIDI, CV), the **part** it will play, then [Add the track] — with a sound in the style and a first clip — or [Remove], which also removes it from every section.

## Editing a sound by hand {#atelier-modifier-son}

[Edit the sound…] opens the editor of the chosen track's sound, a new synth; the sound of a track of the original song belongs to it and is not edited here. The same editor opens from the [Generator](#generer).

Its seven tabs follow the Deluge's menus: **Voice** (engine, play mode, transpose, glide, volume, pan, unison), **Oscillators** (shapes, tuning, levels, pulse width, noise; the modulators in FM), **Filters** (low-pass and high-pass, with their curve), **Envelopes**, **LFO**, **Effects** (reverb, delay, mod FX, saturation, reductions, equaliser) and **Modulation**. Switching to FM turns the filters off, as on the machine.

Each encoder shows the step you would read on the machine, from 0 to 50, and below it **what it is worth on the Deluge**, computed with its firmware's laws: “1.8 s” for a decay of 13, “237 Hz” for a cutoff of 19. An encoder is set by dragging up or down, with the wheel or with the arrow keys; Shift makes the gesture finer, a double-click brings it back to the middle. The envelopes can also be dragged with the mouse, on their curve.

In **Modulation**, each line links a source to a setting, with a depth from −50 to +50 and a polarity; beside it, what the modulation does: “±4.0 octave(s)”, “±0.34 semitone”. [Add a modulation] creates one, [Remove] takes it away.

!!! retenir At rest, an envelope pulls the setting down
    Without polarity, a source goes from −1 to +1: an envelope is worth −1 at rest and pulls the cutoff below its step. Unipolar, it goes from 0 to 1 and only opens.

[Listen] plays the sound as it is set; with [Listen while adjusting], it plays again a moment after each gesture. Under the tabs, a line sums up what has changed. [Back to the original sound] forgets everything, [Cancel] closes without changing anything, [Keep this sound] gives the sound to the track. Nothing is written to the card: the sound will be, with the song. The track is then marked as edited by hand, and its **variations in the style keep your edits**: each one changes in the edited sound what it would have changed in the generated sound. A setting you turned stays turned by as much; a waveform or a filter type you chose stays, unless the variation is meant to change it (“Another timbre”, “Another filter”); a modulation you added stays, a modulation you removed stays removed. A variation that would no longer change anything — the cutoff already at its maximum for “Brighter” — gives its place to the next one.

## The clips {#atelier-clips}

A track has its clips, named A, B, C…: the list says where each one comes from — generated, a variation of another, or taken from the original song — and its length. Below, the clip itself: the rows of a drum kit, from bottom to top, or a synth's notes at their pitch. A line says how many notes it has and in which sections it plays.

- [Play the clip] plays it on the computer, with its track's sound.
- [Vary] opens the menu of variations; the chosen variation is **added** to the track as a new clip, and the original stays.
- [New clip] makes another one, of the length chosen beside it (one, two, four or eight bars), on the song's progression.
- [Delete the clip] removes it; the sections that played it fall silent for that track.

| For a synth | For drums |
|---|---|
| **rhythm** — the same shape, shifted: anticipations, repeated notes | **ornaments** — ghost notes, hi-hats, percussion; the backbone intact |
| **notes** — the same rhythm, other notes: neighbours, fifth, inversions | **fill** — a roll over the end of the last bar |
| **more** — passing notes, pickups, fills | **light** — no snare and no clap, for an intro or an ending |
| **less** — the strong beats alone, held | **breakdown** — no kick: the tension drops |
| **answer** — the first half kept, the second answers it | **doubled** — hi-hats twice as tight |
| **octave** — octave leaps, or the register moved | **half-time** — the snare on the third beat |
| **ending** — the last bar leads back to the start | **build-up** — a roll that speeds up to the end |

A variation keeps the key and the progression: a note that moves stays in the scale, and a bass's fifth is the one of the chord of the moment.

## Playing on the Deluge {#atelier-direct}

[Play on the Deluge] sends the clip to the machine, looping, on the channel set for the Deluge — the one [MIDI Follow](#midi-follow) follows. The Deluge therefore plays it **in the clip open** on the machine. If it is playing, the clip starts at the beginning of its next loop, locked to its clock; when it is stopped, the clip plays at the song's tempo. Another click on the button stops it.

!!! attention When recording, the clip is written in
    With the machine recording (REC), the notes go into the open clip, as if you were playing them: on the Deluge, first open the clip that should receive them. Nothing else is sent — no setting, no file.

The Deluge must be plugged in and connected ([Connecting](#se-connecter)), and MIDI Follow set up on the machine ([Two settings on the machine](#reglages-machine)).

## The song {#atelier-morceau}

The grid shows the whole song: **one row per track, one column per section**, and in each cell the letter of the clip the track plays there. A click on a cell makes the track play its next clip, then silence, then the first one again. A click on a section's header chooses it. Clips taken from a song on the card have a dotted outline.

**The chosen section** is set below: its **name** — which its clips carry on the Deluge — and its **length** in bars, over which its clips loop.

- [Play the section] plays its beginning — eight bars at most —, all tracks together; [Stop] cuts the listening.
- [Add a section] adds one after the chosen one, with the same clips; [Remove the section] removes it.
- The two arrows move it one step in the song.
- [Genre structure] replaces the sections with the genre's, with their variations. Starting from one of your songs, its sections stay, and the genre's are added after them.

A line sums it all up: the number of sections, of bars, the duration and the tempo.

## Writing the song {#atelier-ecrire}

[Write the song] turns it into a Deluge song, in `SONGS`: one Deluge section per project section, each with its clips and its number of repeats, and the complete arrangement for the SONG view. The synths carry their sound; the drums, a kit built from your samples, or the one you chose on the card; the MIDI and CV tracks, their channel. The route is that of any [written song](#parcours-morceau): a name, the plan, then the writing of a new file.

## Starting from a song, and completing it {#atelier-completer}

[Start from a song…] opens a song from the card in the studio — the latest received from the Deluge at the top of the list. Its tracks, its clips, its tempo and its scale become the project's; its chord progression is read from its notes, so that the new clips fit it. Its clips can be varied like the others — a variation is always a new clip —, and tracks, clips and sections can be added.

[Complete the song] then writes a **new version**: “Cool1 5” after “Cool1 4”. It contains the original song **byte for byte**, plus what you added: the new tracks, their clips, and the new sections with theirs. The plan details every addition before writing. The written file is read back at once: if the original song is not intact in it, nothing is written.

!!! retenir The original song is never rewritten
    The new version is a file next to the old one; load it on the Deluge like any song. The existing sections keep their length and their clips; they receive those of the new tracks, and of a track that played nothing in them. A track that already has its clip there keeps it: in grid layout, the Deluge shows only one per track and per section. Put the new one in a new section — the plan flags each case.

The song must come from firmware 1.2 or later. An older song, or one in the 2.x format, is refused: save it once on the Deluge, which converts it, then try again. The new notes are written in the song's format; the Deluge knows 24 sections at most in firmware 1.3, 12 before.

## Working alongside the machine {#atelier-simultane}

The studio and the Deluge work on the same song in two ways, which complement each other:

1. **Live** — a clip made in the studio goes to the machine with [Play on the Deluge], locked to its bar; when recording, it goes into the open clip. The song grows on the machine itself.
2. **Through the file** — save the song on the Deluge; it reaches the application through [synchronisation](#carte-dans-le-deluge). Open it with [Start from a song…], compose, then [Complete the song]: the new version goes back to the card, and loads on the machine.

# Toolbox {#boite-a-outils page=Toolbox}

> The questions you ask yourself mid-song, usually answered with a calculator and a notebook.

The page is called “Tools” in the left column. Six tabs; none needs the card, except the search by key and the drum sounds used for listening.

## Theory {#theorie}

**Scale.** Pick a **Root** and a **Scale** among twenty-seven — from the classic modes to scales from around the world (hijaz, hirajoshi, in sen…). The keyboard highlights its notes, the list names them, and the `<modeNotes>` line gives the scale as the Deluge writes it in its songs; [Copy] puts it on the clipboard.

**Chords of the scale.** The table gives each degree, its chord and its notes; a click on a row highlights the chord on the keyboard.

**Progression.** Pick a **Mood** (pop, melancholy, house, deep, techno, trance, ambient, jazz, blues, epic, tense, bright), a **Colour** — triads, sevenths, ninths, suspended chords, or “according to the mood” — and a number of **Bars** (2 to 16), then [Suggest]. The chord sequence appears in the list.

**The accompaniment** lays this progression out in time. **Genre** sets the chord rhythm, the bass style, the arpeggio, the tempo and the sounds used for listening; **Chords** and **Bass** can force a style (chords held, in half notes, off-beat, as stabs, charleston; bass on the root, pulsing, off-beat, rolling, in octaves, syncopated, walking, acid). The **Add** line ticks the optional parts: [Arpeggio], [Melody], [Drums].

- [Listen] plays the progression and its accompaniment, on sounds generated for the genre; [Stop] cuts it. Nothing is written.
- [Another chord] replaces the chord selected in the list with another of the same function; the rest doesn't move.
- [Another melody] draws another melody over the same chords, and plays it.
- [As MIDI] writes a `.mid` file: one track per part, each on its own channel, drums on track 10.
- [As a song] writes a new song into `SONGS`: one instrument and one clip per part, with the sounds heard while listening; the clips loop together as soon as you press PLAY.

## Rhythm {#rythme}

- **Genre** and **Bars** (1 to 4), then [Genre pattern]: a typical rhythm appears in the grid.
- **Euclidean**: a number of **hits** spread as evenly as possible over a number of **steps**, shifted by the **rotation**; [Add the track] adds it to the current pattern.
- **Groove**: sampler swing in percent (MPC 54 % to 71 %), “laid-back” playing behind the beat or “ahead” of it; the **Swing** slider adds more freely. [Apply] always starts from the straight pattern: a second click doesn't stack up. When possible, the status bar gives the equivalent swing setting on the Deluge.
- [Variation] varies the pattern without touching its backbone: kick, snare and clap stay.
- [Listen] plays the pattern twice, with the card's samples when it has some, otherwise a synthesised kit; **BPM** sets the tempo. [Stop] cuts it.
- [As MIDI] writes the pattern, percussion on channel 10; [As a song] writes a new song: a kit of your samples and a clip playing the pattern.

The grid can be edited by clicking. Below it, the pattern as text, to copy into a notebook.

## Calculator {#calculatrice}

- **Tempo**: for the chosen BPM, the length of a bar, and a table of divisions — straight, dotted, triplet — in milliseconds, with the frequency of an LFO locked to it. Enough to set a delay or an LFO by hand.
- **Deluge syncLevel**: how the value written in files maps to the rhythmic division (7 = sixteenth note).
- **Memory and length**: the weight of a recording according to its length, rate, resolution and channels — and how many minutes the space left on the card allows you to record in that format.

## Harmonic mixing {#mixage-harmonique}

The **Camelot wheel**: each major key, its relative minor, their codes and the compatible keys. Two tracks blend without a wrong note if their codes are identical, one step apart, or if they swap major and relative minor.

**Search the library**: type a key (Am, C, F#m), then [Search] — the list shows the card's samples in that key or a compatible one, with their tempo. Acoustic analysis is required.

## Arrangement {#arrangement}

A **structure template** per genre: intro, build-up, theme, breakdown, finale… The table gives each section, its length in bars, its duration, its position, and the **parts** it plays; the total shows in minutes at the chosen tempo.

The sketch reuses the Theory tab's progression if there is one, and the Rhythm tab's rhythm if it is of the same genre; otherwise the genre's own. A sentence under the table says what it uses.

- [Play the section] plays the start of the selected section — eight bars at most —, with only the parts of its role.
- [Sketch as MIDI] writes the whole song to a MIDI file, one track per part, with section names as markers.
- [Sketch as a song] writes a **sectioned** song into `SONGS`: each section of the template becomes a Deluge section, with its clips and its number of repeats.

## Cheat sheet {#aide-memoire}

The Deluge values you always forget: rhythmic resolution, the scale of parameters and patch cables, the note format, probability conditions, scales, `syncLevel`, the arpeggiator, kit rows, file name rules, firmware, expected folders, sample rate.

!!! astuce The Deluge's tempo
    When the connected Deluge plays, its clock can set the tempo of this page's listening, MIDI files and songs: the [The tools follow the Deluge's tempo] box in the settings, ticked by default.

# Card health {#sante page=Health}

> What is wrong with the card, and how to repair it — always showing the plan first.

## Diagnosing {#diagnostiquer}

[Diagnose] looks for problems in the index already built: it **doesn't reread the card** and takes under a second. It starts by itself on the first visit. A diagnosis only makes sense after a scan: without an index there is nothing to judge.

The result shows in the [Report] tab: the **score out of 100**, a verdict, the list of **problems** sorted by severity, and the **details** of the one you select — what it means, the files concerned, and how to fix it.

[[figure sante | The health score, and what its colour says on the dashboard. | 90 and above ; card in very good shape ; 70 to 89 ; a few things to keep an eye on ; 40 to 69 ; a card that needs a clean-up ; under 40 ; needs a serious tidy-up]]

The score starts at 100 and loses **5 points per kind of error** and **2 per kind of warning**: it counts categories of defects, not files. Three hundred junk files are a single problem to solve, not three hundred.

## What the diagnosis can find {#controles}

| Problem | Severity | Automatic fix |
|---|---|---|
| Standard folders missing | error | yes: create them |
| Several firmware files at the root | error | — |
| Samples referenced but missing | error | yes: relink to the replacement with the same name |
| Unreadable XML files | error | — |
| Low free space | warning | — |
| Duplicate samples | warning | yes: keep only one |
| XML files repaired when read | warning | — |
| Problematic file names | warning | yes: rename |
| Paths too long (over 200 characters) | warning | — |
| Clipped samples | warning | yes: give back headroom |
| DC offset | warning | yes: remove it |
| Silent samples | warning | — |
| Junk files (`._*`, `.DS_Store`, `Thumbs.db`…) | warning | yes: delete them |
| No backup | warning | — |
| Samples never used | information | yes: archive them into `_UNUSED` |
| Unusual sample rates | information | yes: convert to 44.1 kHz |
| Very large samples (over 20 MiB) | information | — |
| Stereo drums | information | yes: turn to mono |
| Very deep folder tree (over 8 levels) | information | — |
| Non-audio files in `SAMPLES` | information | — |
| Empty folders | information | yes: delete them |

An XML file with several roots is normal in older firmware: it is not reported. The clipping, DC offset and silence checks require the acoustic analysis.

## Fixing automatically {#corriger}

In the report, **tick** the problems to fix — only those that can be fixed have a box —, then [Fix automatically]. The **exact plan** is shown: every file, every operation, in red what deletes. Nothing is done before your consent.

The order of operations is dictated by caution: broken references are repaired **before** any archiving, because a sample looks unused precisely when the reference pointing to it is broken.

[Export the report] saves the diagnosis as an HTML page, wherever you choose.

## Duplicates {#doublons}

Groups of **strictly identical** files, checked byte by byte — a partial fingerprint isn't enough: it once declared identical files that differed. The table gives each group, its files and the space wasted.

[Copy to keep] decides which one to keep: [Shortest path], the longest, [Most used], the oldest or the newest. [Delete duplicates] first shows the exact list of files to delete; presets that referred to a duplicate are redirected to the copy kept.

## Missing {#manquants}

Samples a preset, kit or song asks for but that are missing from the card — with who asks for them.

- [Find replacements] looks on the card for files that could replace them, by name, size and fingerprint. Nothing is changed.
- [Relink automatically] fixes the presets so they point to the replacement found — **only** when it has exactly the same file name: redirecting to a similar name would be a gamble, not a repair. A `.bak` copy stays next to each changed file.

## Unused {#inutilises}

Samples no file on the card refers to, with their length and size. It is not a defect: a library keeps sounds in reserve. [Archive into _UNUSED] **moves** them into an `_UNUSED` folder at the root of the card; nothing is deleted, everything can be recovered.

## Backups {#sauvegardes}

A backup copies the card into the **backups folder** (Settings ▸ Write safety), into a dated subfolder.

- By default it copies the **songs, presets and kits**, with the machine's settings and favourites (the `SETTINGS` folder of firmware 1.3): a few megabytes, under a second — so you can back up often.
- [Include the samples] adds the sounds: over a gigabyte on a well-filled card, best kept for full backups.
- [Compress as .zip] packs it into an archive, slower to write, much smaller.

[Back up now] creates it. In the table — date, label, number of files, size — pick a backup, then:

- [Compare] shows what has changed since: files modified, added, removed;
- [Restore] puts the backup's files back on the card. The number of files replaced is announced first, and their current versions are set aside in a “before restoration” backup.

!!! attention Restoring overwrites
    It is the only action on the page that replaces the card's files with others. It asks for confirmation and keeps the replaced versions — but check with [Compare] first.

!!! pro Two backups, two uses
    These dated backups are made **by the application**. The “card backup” declared in Settings ▸ Deluge card is something else: your full copy of the card, which the application reads without ever writing to it, and updates on request (see [The card backup](#sauvegarde-carte)).

# Settings {#reglages page=Settings}

> The card's location, the connected Deluge, listening, scanning, write safety and appearance.

It is the only page that works without a card: it is where you designate one. [Detect cards], in the header, looks for a Deluge card on the connected drives. The sections, from top to bottom:

## Deluge card {#reglages-carte-deluge}

The state of the link — does the Deluge open its card over USB? is there a working copy, and where? — and its commands: [Create the working copy], which becomes [Sync now] once the copy exists; [Deletions to confirm…], when files deleted in the application still exist on the card; the [Sync automatically when the Deluge is plugged in] box (ticked by default); [Choose the backup…] and [Update the backup]. It is all explained in the chapter [The card stays in the Deluge](#carte-dans-le-deluge).

## Other card location {#reglages-autre}

For a card in a reader on the PC, or a folder: the path field, checked as you type, [Browse…], [Use this card], the detected cards and the **recent paths**. See [Designating the card](#designer).

## Connected Deluge {#reglages-deluge}

The state of the MIDI link and what the machine said about itself (firmware, round-trip time); the **MIDI output** and **MIDI input** — “Find the Deluge automatically” almost always does; the **Channel** (1 by default); three boxes: [Connect as soon as the Deluge appears] (ticked), [Play presets on the Deluge rather than on the computer] (unticked) and [The tools follow the Deluge's tempo] (ticked); the [Connect], [Play a C], [All notes off] and [Deluge Live…] buttons; and finally the settings to make **on the machine**. See [Connecting the Deluge](#brancher).

## Listening {#reglages-ecoute}

The **Audio output** for listening (the default device, or another), the audio engine in use, the **Preview volume** — with no effect on the Deluge —, and the [Play the selected sample automatically] box (ticked).

## Card scanning {#reglages-analyse}

The [Compute fingerprints (duplicate detection)], [Acoustic analysis (tempo, key, levels)] and [Update the index at start-up] boxes, the [Reset the index] button, and the state of the index: how many samples, presets, kits and songs, its size, the date of the last scan. See [Scanning and the index](#analyse).

## Write safety {#reglages-surete}

Two safeguards, ticked by default — **leave them on**:

- [Ask for confirmation before any write]: nothing is written to the card without a question first;
- [Create a .bak copy before rewriting an XML]: every rewritten preset or kit leaves a dated copy next to it.

Below, the **backups folder** for backups made from the Health page; when empty, they go into the application's configuration folder.

## Appearance and About {#reglages-apparence}

**Appearance**: six colours for the front panel — gold, cyan, mint, amber, magenta, indigo. It tints the top bar, the menus and the windows opened outside the pages; each page keeps its own colour. **About**: the version, and the **configuration folder**, which [Open] shows in Explorer.

@partie deluge PAD_GREEN | The connected Deluge | The machine at the end of the USB cable: its card, its screen, its tempo

# Connecting the Deluge {#brancher icone=midi}

> A USB cable, two settings on the machine, and the application can play on the Deluge, read its screen and follow its tempo.

## What you need {#brancher-prerequis}

- A USB cable between the Deluge and the computer, under Windows.
- The **community firmware**: it is what answers the application's messages (version, screen). With version **1.3** or newer, the card also opens over the cable.

## Connecting {#se-connecter}

Plug in the cable: the “Deluge” chip in the top bar turns **gold**. If the [Connect as soon as the Deluge appears] box is ticked — the default —, the application connects by itself and the chip turns **green**. Otherwise a click on the gold chip connects; [Connect], in the settings, does the same.

The Deluge exposes several MIDI ports: the application sends notes and controllers through the first and talks SysEx through the third. The machine then gives its version, and the round-trip time is measured. Unplugged midway, the link closes cleanly, and the status bar says so.

!!! retenir Connecting plays nothing
    On connection, the application asks the machine for its version, measures the round trip and asks whether its card opens over USB — read-only messages — and nothing else. No note is sent unless you ask for it.

## Two settings on the machine {#reglages-machine}

The community firmware's **MIDI Follow** mode is off on a new machine. Once and for all, in the Deluge's settings menu ([[SHIFT + SELECT]]):

1. **MIDI ▸ MIDI-Follow ▸ Channel ▸ Channel A** = the application's channel (1 by default). Without this setting, the machine ignores what the application plays.
2. **MIDI ▸ MIDI-Follow ▸ Feedback ▸ Channel** = A, so the settings of the selected sound come back to the application.

The MIDI clock comes out by itself: **MIDI ▸ Clock ▸ Output** is on from the factory. A kit answers from note 36 upwards (**MIDI ▸ MIDI-Follow ▸ Kit Root Note**). These paths are the same in firmware 1.2.1 and 1.3.

With firmware 1.3, the machine writes these settings to its card, in `SETTINGS/MIDIFollow.XML`: the application reads them there, and the [Deluge Live](#en-direct) window ticks them off as soon as it opens, without waiting for the machine to show them.

## Checking the cable {#verifier}

[Play a C] sends a half-second middle C to the selected instrument: if you hear it, everything is in place. [All notes off] releases every note on every channel — the emergency button if a sound gets stuck.

## Listening on the machine {#ecouter-sur-la-machine}

Tick [Play presets on the Deluge rather than on the computer]: [Listen], on the Presets and Generator pages, then plays **the machine's engine** instead of the computer's approximation; [Play the kit] sends the test pattern to the Deluge. This listening never switches on by itself: sending sound into a machine plugged into an amplifier must not come as a surprise.

What goes out: the preset's settings **that a knob controls** — filters, envelopes, effects, levels, some fifty of them —, then **the short phrase the computer would play**, chosen from the preset's category: four low notes for a bass, a spread chord for a pad, a rise for a lead. One note every 0.55 seconds, each held for half a second. What does not: the oscillators' waveform, a sample, the arpeggiator mode — no controller carries them. So you hear **the oscillators of the selected instrument, set like the preset**. A preset with a very slow attack may be barely audible in half a second.

The Deluge **loses** controllers that arrive while it is handling the previous ones, or while it is sending the image of its screen. So the application waits until it has read each setting before sending the next: the listening goes out in about a second. With the [Deluge Live](#en-direct) window open, the screen mirror goes quiet during the sending, which adds up to two seconds.

!!! retenir The machine's Takeover setting
    [[SHIFT + SELECT]] ▸ MIDI ▸ **Takeover** decides what the Deluge does with a value it receives. In **Jump** (the factory setting), it takes it. In **Pickup** or **Scale**, it ignores it until the value has “caught” the knob's position. The application makes each knob catch up: when the MIDI Follow feedback has told it where the knob is, it starts from that position; otherwise, with the machine stopped, it sends the knob briefly through both extremes. With the machine playing and the position unknown, the value goes out alone — in Pickup or Scale, it is then ignored. **Relative** mode, made for endless encoders, is not supported.

!!! attention The Deluge plays the instrument selected on it
    No MIDI message can tell it “load this preset”: it is a limit of the machine. The settings of the preset being played go out as MIDI Follow controllers just before the note, and apply **to the instrument selected on the Deluge**. Its sound therefore changes until you reload it — nothing is saved to the card unless you save on the machine. To listen without risk, load an unimportant song first.

## The Deluge's tempo {#tempo}

When the machine plays, its MIDI clock gives its tempo. With the [The tools follow the Deluge's tempo] box (ticked by default), the toolbox tempos take it as soon as its rounded value changes; a page opened while the machine plays takes it once, on its first visit — after that, you decide.

## The controller table {#midi-follow}

The controllers MIDI Follow mode understands are read from your card, in `SETTINGS/MIDIFollow.XML` with firmware 1.3 — at the root of the card with older firmware. Without that file, the factory assignments apply: 52 controllable parameters. The firmware 1.3 file declares more — 79 on the machine used to check this manual, arpeggiator settings included. The Connected Deluge section of the settings says which of the two tables is in use, and how many parameters can be controlled.

# The card stays in the Deluge {#carte-dans-le-deluge icone=refresh}

> With firmware 1.3, the card no longer leaves the machine: the application works on a copy kept in step with it, over the USB cable.

[[figure flux | The Deluge, the working copy and the backup. | THE DELUGE ; its SD card stays inside ; USB cable, firmware 1.3 ; WORKING COPY ; on the PC, kept in step with the card ; on connection, after every write, on returning to the window — never while the machine plays ; DELUGE COMPANION ; BACKUP ; your full copy of the card, read and never written by everyday work ; updated on request, nothing is ever deleted]]

## Why a working copy {#pourquoi-copie}

Reading thousands of files over the USB cable would take hours: it reads about 170 KB per second, and writes 60. Going through their list, on the other hand, takes only a few seconds — 3.4 s for nearly 3,000 files, measured on a real card. So the application keeps a **working copy** of the card on the computer, and keeps it in step by exchanging **only what has changed**: what the Deluge has recorded **comes down**, what the application has created or changed **goes up**.

## Creating the working copy {#creer-copie}

Once, with the Deluge connected: Settings ▸ Deluge card ▸ [Create the working copy]. The **plan** shows first: how many files will be **taken from your backup** (a fast local copy), how many will come **over the cable**, and how long it will take. A file in your backup identical to the one on the card doesn't need to cross the cable.

The copy then becomes the application's card, and the scan starts. The screen in the top bar reads “DELUGE CARD · WORKING COPY”.

!!! retenir What creating the copy writes to the card
    Nothing, except the date of the files the Deluge has recorded: the machine has no clock and dates everything at zero. That date then shows what it rewrites. Your backup is only read.

## When syncing happens {#quand-synchroniser}

With the [Sync automatically when the Deluge is plugged in] box, the application exchanges by itself:

- **on connection** of the Deluge;
- **after every write** by the application — two seconds after the last one. Only the folders the application touched are read again on the card: a few hundredths of a second, instead of the three and a half seconds of a full walk. What you recorded on the machine comes down on connection, on returning to the window, or on request;
- **on returning to the window**, at most every thirty seconds, to receive what you have recorded on the machine;
- and **never while the machine plays**: its card is busy playing. A transfer in progress stops between two blocks, and resumes when playback stops.

At any time: [Sync] on the dashboard, [Sync now] in the settings, or Tools ▸ Sync with the Deluge [[Ctrl+Shift+D]]. The screen says what is waiting: “WORKING COPY · 3 TO SEND”, or “WORKING COPY · SYNCING…”.

## The rules of exchange {#regles-echanges}

| Situation | What happens |
|---|---|
| a file changed on the Deluge | it comes down into the working copy |
| a file created or changed in the application | it goes up to the card |
| a file changed **on both sides** | both versions are kept: the Deluge's keeps the name, the PC's becomes “… (PC)” |
| a file deleted in the application | it only disappears from the card **with your consent**: [Deletions to confirm…] |
| a file deleted on the Deluge | the working copy's version goes into its history, never into the bin |
| the Deluge unplugged during a transfer | the exchange resumes at the next connection |

Each exchange is written to the application's log, file by file.

## The card backup {#sauvegarde-carte}

Settings ▸ Deluge card ▸ [Choose the backup…] designates the folder that holds your **full copy of the card**. The application **reads** it — to create the working copy without sending everything over the cable — but **never writes to it** during everyday work. Opened as a card, it opens **read-only**: the screen reads “BACKUP · READ-ONLY”.

[Update the backup] brings in what is new on the card: the plan announces the files added, the files replaced — **the old version kept alongside** — and those the card no longer has, which are **kept**. Nothing is ever deleted from it. When the backup is behind the card, “Do this now” suggests it.

## With older firmware {#ancien-firmware}

With firmware 1.2.1, the card doesn't open over the cable. Slide it into a reader on the computer and set it in Settings ▸ Other card location: the application works on it directly. The MIDI link — listening on the machine, screen, tempo — works anyway.

# Exchanging files {#echanges icone=import}

> Putting sounds and presets from the PC on the card, and getting out what the Deluge has recorded.

## Sending to the Deluge {#envoyer}

With the card staying in the machine, Explorer can no longer reach it: the application puts your files on it. Four ways in, a single route:

- **drag files or a folder anywhere onto the window** — a downloaded pack, a bounce from your music software. A green veil announces “Drop to send to the Deluge” and where the files will go;
- File ▸ Send files to the Deluge… [[Ctrl+I]];
- File ▸ Send a folder to the Deluge… [[Ctrl+Shift+I]];
- [Send to the Deluge…] on the Samples page, which sends into the folder chosen in its tree, or [Send files…] on the dashboard.

## The plan before sending {#plan-envoi}

Before anything is copied, the **plan** shows: where each file goes, what is already on the card, what the Deluge would refuse, and **how long the cable will take** — about 60 KB/s: an 18 MB pack takes five minutes, a 271 MB one nearly an hour and twenty minutes. Beyond half an hour, the plan suggests sending only part of it. A list sets the `SAMPLES` folder where sounds outside a pack go. [Send] starts the copy; [Cancel] copies nothing.

The rules:

- a pack **shaped like a card** (`SAMPLES`, `SYNTHS`…) keeps its paths, which its presets refer to;
- **nothing existing is replaced**: an identical file is left alone; a different file with the same name gets the new one numbered (“Kick 2.wav”);
- names become **transferable**: no accents or forbidden characters (“Été” becomes “Ete”), and the pack's presets follow;
- a file the Deluge would refuse — a WAV with an extended header, as much software writes — is **converted with no audible loss**;
- what isn't for the Deluge — an MP3, a four-channel file, documentation — stays on the PC, and the plan says why.

The files then go to the Deluge in the background, or at its next connection. The backup, open read-only, refuses anything sent to it: “Nothing is written here”.

!!! attention The Deluge must not play while sending
    While the machine plays, nothing goes through: the transfer stops between two blocks, and resumes when playback stops.

## From the Deluge to the PC {#vers-le-pc}

- The **The Deluge and the PC** panel on the dashboard lists what has arrived from the machine; a click opens each file on its page.
- On the Samples page, **drag a sound** to Explorer or your music software: it receives a copy, as it is in the working copy. A recording made on the Deluge can be reworked on the PC this way.
- The exports — [Song as MIDI], [Collect…], [Pattern as MIDI] — write on the computer, wherever you choose.

# Deluge Live {#en-direct icone=wave}

> A window to keep next to the application: the machine's screen, its tempo, the notes of its MIDI tracks, and the selected sound.

It opens from Tools ▸ Deluge Live [[Ctrl+D]], from [Deluge Live…] in the settings, or with a click on the green chip. It only **reads**: nothing is written to the machine.

## Its four panels {#panneaux-direct}

| Panel | What it shows |
|---|---|
| The machine's screen | the Deluge's OLED screen, mirrored the moment it changes |
| Tempo and notes | the tempo read from the clock, “Playing” or “Stopped”, the notes held on a Deluge **MIDI track** and the chord they form. A synth or kit played on the pads does not send its notes: “No note received” does not mean a fault |
| Sound selected on the machine | the settings the MIDI Follow feedback sends back when you change instrument or turn a knob |
| Settings to make on the Deluge | the list of required settings, ticked off as the link observes them |

## Its buttons {#boutons-direct}

- [Mirror the screen] starts or stops the mirroring. It starts by itself on opening. When stopped, the window says so plainly: it never shows a frozen image you could mistake for the machine.
- [Say hello] shows “HELLO SYSEX” on the Deluge for a moment: a way to check you are talking to it.
- [Check] asks the machine for its version again and measures the round trip.
- [All notes off] releases every note.
- [Connect] or [Disconnect], and [MIDI settings…], which leads to the Connected Deluge section of the settings.

Closing the window stops the screen mirroring.

!!! attention Firmware 1.3's screensaver
    When idle, a Deluge running 1.3 replaces its screen with an animation — streaks falling diagonally (“Deluge” mode), a starfield, or black. The mirror faithfully shows that animation, and the [Say hello] message stays hidden underneath. Only a gesture on the machine — a button, an encoder — wakes it; neither MIDI nor the application can. Its mode and delay are set in **Settings ▸ Defaults ▸ Screensaver**.

# Writing songs for the Deluge {#morceaux-pour-le-deluge icone=song}

> Every creative tool can write what it has produced as a Deluge song: a new file in SONGS, which the machine loads like any other.

## The nine buttons {#boutons-morceau}

| Where | Button | What the song contains |
|---|---|---|
| Tools ▸ Theory | [As a song] | one clip per part — chords, bass, arpeggio, melody, drums —, with the sounds heard while listening; everything loops together from PLAY |
| Tools ▸ Rhythm | [As a song] | the pattern shown, played by a kit of your samples |
| Tools ▸ Arrangement | [Sketch as a song] | one Deluge section per template section, each with its clips and number of repeats |
| Kits | [Pattern as a song] | the selected kit, as it is on the card, and the test pattern |
| Generator | [Try in a song] | the sound in context: a phrase made for its role, and the genre's drums |
| Generator ▸ Drum kit | [Kit as a song] | the kit built and its genre's rhythm |
| Samples ▸ Slice… | [Write as a song] | the slices' kit, and a clip replaying the loop |
| Studio | [Write the song] | the composed song: one Deluge section per section, their clips, their repeats and the complete arrangement |
| Studio | [Complete the song] | your song byte for byte, plus the tracks, clips and sections added — in a new version |

## The route {#parcours-morceau}

1. The application builds the song; a usage error — nothing to write, no card — is announced before any question.
2. It asks for its **name**, cleaned up for the card.
3. It shows the **plan**: the file, the instruments, the clips, the samples missing from the card.
4. It writes, then indexes the new song: it appears at once on the Songs page.
5. On the working copy, the connected Deluge receives it **by itself**: two seconds after the write, the sync reads again only the folders touched — a few hundredths of a second —, then sends the file at about 60 KB/s: half a second for a 33 KB song, three for a 165 KB sketch. It then loads on the machine like any other song.

**No existing file is replaced**: a name already taken is numbered.

## Playing a sketch {#jouer-esquisse}

A sectioned sketch plays in two ways on the machine. **PLAY** loops the first section; launch the next one, and the rest follows on to the end. The **arrangement** view (SONG key) plays the whole song in one go. Repeating parts fit in short clips — four bars of chords, one bar of drums —, the way you build them on the machine.

!!! retenir Tried on the machine
    On 22 October 2026, three songs written by the application — a progression with its drums, a six-section sketch, a pattern on the TR-808 kit — were sent over the cable, loaded and played on a Deluge running firmware 1.3. The format written is the one of community firmware 1.2.1, which 1.3 also reads, and the conversions of older presets have been compared with songs recorded on the machine. Each song is a new file: it touches nothing the card already holds.

@partie reference PAD_PINK | Reference | The safeguards, the shortcuts, common problems and the vocabulary

# The no-destruction rule {#non-destruction icone=check}

> The application is built around one principle: it changes nothing unless explicitly asked to.

[[figure plan | The four stages of any write to the card. | You ask ; a click on a button that writes ; The plan ; every file, every operation, up front ; Your consent ; nothing goes ahead without it ; The write ; with a .bak copy of any rewritten XML]]

## The safeguards {#garde-fous}

- **Everything is simulated first.** Tidying, repairing, deleting, processing, sending: the plan is shown operation by operation, and nothing is touched before a confirmation click. A plan that deletes or changes the length of files says so in red.
- **Every rewritten XML leaves a dated `.bak`** next to it (Settings ▸ Write safety).
- **A duplicate is only deleted if it is identical byte for byte**, never on the strength of a partial fingerprint.
- **Songs are never rewritten.** The application creates new ones; it doesn't change yours. Even [Complete the song] writes a new version, next to the old one.
- **The original dialect is preserved**: a file from older firmware is rewritten in its own format, and the Deluge keeps reading it.
- **Nothing is lost**: archiving moves into `_UNUSED`, audio treatments keep the originals in `_BACKUP`, restoring keeps the replaced versions, syncing files away what it removes in the history.
- **The card backup is only read**, and never receives a deletion.

## What writes to the card {#ce-qui-ecrit}

Here, all together, are the commands that write to the card. Each one shows its plan or asks a question before writing — only [Save to KITS] writes straight away when the chosen name is free, since it replaces nothing:

| Page | Commands |
|---|---|
| Samples | [Process…], [Write the kit], [Export as files…], [Write as a song], [Send to the Deluge…] |
| Presets | [Duplicate] |
| Kits | [Pattern as a song] |
| Generator | [Save to SYNTHS], [Generate a batch into a folder…], [Try in a song], [Save to KITS], [Kit as a song] |
| Studio | [Write the song], [Complete the song] |
| Tools | the three “as a song” buttons |
| Health | [Fix automatically], [Delete duplicates], [Relink automatically], [Archive into _UNUSED], [Restore] |
| Settings | [Create the working copy], [Sync now], [Deletions to confirm…], [Update the backup] — the last one writes to your backup |

The Songs page, for its part, never writes to the card.

# Keyboard shortcuts {#raccourcis icone=list}

> The key combinations of the main window and of this manual.

| Shortcut | Action |
|---|---|
| [[Ctrl+1]] to [[Ctrl+9]], [[Ctrl+0]] | go to the matching page, in the column's order; [[Ctrl+0]] for the tenth, Settings |
| [[Ctrl+R]] | scan the card |
| [[Ctrl+F]] | search for a sample, from any page |
| [[Ctrl+O]] | choose the card |
| [[Ctrl+G]] | the generator |
| [[Ctrl+,]] | the settings |
| [[Ctrl+I]] | send files to the Deluge |
| [[Ctrl+Shift+I]] | send a folder to the Deluge |
| [[Ctrl+D]] | Deluge Live |
| [[Ctrl+Shift+D]] | sync with the Deluge |
| [[Ctrl+B]] | collapse or unfold the left column |
| [[Space]] | listen, or stop listening |
| [[F1]] | this manual, at the chapter of the page shown |
| [[Ctrl+Q]] | quit |

In the manual window:

| Shortcut | Action |
|---|---|
| [[Ctrl+F]] | search the manual |
| [[Enter]] or [[F3]] | next match |
| [[Shift+F3]] | previous match |
| [[Esc]] | clear the search, then close the manual |

Help ▸ Keyboard shortcuts recalls the first list in a small window.

# Questions and troubleshooting {#depannage icone=warning}

> Common situations, and what to do.

## The pages are empty {#pages-vides}

No card is set, or it hasn't been read yet. Set it ([Designating the card](#designer)), then [Scan]. The screen in the top bar tells you where things stand: “NO CARD”, or “CARD · not scanned yet”.

## “… does not contain a Deluge folder tree” {#pas-une-carte}

You designated a folder that doesn't contain at least two of the `SONGS`, `SYNTHS`, `KITS`, `SAMPLES` folders. Go up one level: the card's **root** is needed, not one of its folders.

## I can't hear anything {#pas-de-son}

- Is the **sounddevice** package installed? Without it, listening on the computer is silent.
- Check the **Audio output** and the **Preview volume** in Settings ▸ Listening.
- If “Play presets on the Deluge” is ticked, the sound comes **from the machine**: check its MIDI Follow settings and its volume.

## A button stays grey {#bouton-gris}

It is waiting for a selection: a sound, a preset, a row. Its tooltip says what it will do. [Slice…] and [Similar sounds] want a single sound; [Scan] wants a card.

## The “Deluge” chip stays grey {#pastille-grise}

The computer doesn't see the machine. Check the cable — some USB cables only carry power —, that the Deluge is switched on, and that no other software holds its MIDI ports. Outside Windows, the MIDI link isn't available.

## The Deluge ignores what the application plays {#deluge-ignore}

The machine's **MIDI ▸ MIDI-Follow ▸ Channel ▸ Channel A** setting must match the application's channel (1 by default, Settings ▸ Connected Deluge). Remember: the machine plays **the instrument selected on it**. [Play a C] lets you check.

## Listening on the Deluge does not change the sound {#ecoute-sans-effet}

- The Deluge applies the settings to **the instrument selected on it**: is it the one you are listening to? In song view, it is the last clip you opened.
- [[SHIFT + SELECT]] ▸ MIDI ▸ **Takeover** is set to **Relative**: the application cannot talk to it that way. Choose Jump, Pickup or Scale.
- The machine is playing, the MIDI Follow feedback is off, and Takeover is set to Pickup or Scale: the values are ignored. Stop playback, or turn the feedback on (MIDI-Follow ▸ Feedback ▸ Channel = A).

To see what the machine applies, turn on **MIDI-Follow ▸ Display Param**: the name and value of each setting received appear on its screen. See [Listening on the machine](#ecouter-sur-la-machine).

## The mirrored screen shows falling streaks {#economiseur}

That is firmware 1.3's screensaver: the machine is idle, and the mirror shows exactly what it displays. Touch a button or an encoder on the Deluge to wake it; Settings ▸ Defaults ▸ Screensaver sets its mode and delay.

## “No SysEx reply” {#pas-de-sysex}

The Deluge didn't answer the application's questions: it runs the official firmware, or other software holds its SysEx port. Notes still go through; the version, the screen and the card over USB need the community firmware.

## “Similar sounds” refuses to search {#sons-proches-refuse}

The selected sound has no acoustic measurements. Tick “Acoustic analysis” in Settings ▸ Card scanning, then scan again. The same goes for the sounds' key and the search by key.

## The Deluge is playing, and nothing syncs {#sync-attend}

That is intended: the card is busy playing, and the application waits for playback to stop before exchanging. The status bar says so.

## The application's view of the card is out of date {#index-ancien}

Files were copied onto the card outside the application. [Scan] rereads what has changed. If the index really seems inconsistent, [Reset the index] rebuilds it, without touching the card or your ratings.

## Where is the log? {#journal}

In the configuration folder, the `app.log` file: Settings ▸ About ▸ [Open]. An unexpected error is shown in a dialog, and its full trace is written there. The log stays in French whatever the language: it is for diagnosis.

## The application closed during a task {#fermeture}

Nothing half-written stays on the card: an interrupted backup is deleted so it can't pass for complete, a sync resumes at the next connection, and a sample treatment keeps its originals in `_BACKUP`.

# Glossary {#glossaire icone=tag}

> The words of the application and of the Deluge, one sentence each.

| Term | Definition |
|---|---|
| Scan | the reading of the card that fills the index; it changes nothing |
| Acoustic analysis | the measurements taken on every sound: tempo, key, levels, timbre |
| Arrangement | the Deluge view where the song unfolds on a timeline |
| Patch cable | a link between a source (LFO, envelope, velocity…) and a parameter |
| Camelot | a key notation that shows at a glance which keys blend |
| Clip | a loop of notes for one instrument, on the session grid |
| DC offset | a shift of the waveform above or below zero; it wastes headroom |
| Working copy | the copy of the card the application keeps in step with it over USB |
| Diagnosis | the search for problems in the index; it doesn't reread the card |
| Duplicate | a file strictly identical to another, byte by byte |
| Clipping | a saturated sound whose peaks were cut off at recording |
| Fingerprint | a summary of a file's content, which recognises duplicates |
| Community firmware | the Deluge's open firmware (c1.x versions); it answers the application's messages |
| Seed | the number that makes a generation reproducible |
| Index | the application's database about the card; it lives on the computer |
| Kit | a drum instrument: one row per sound |
| MIDI Follow | the community firmware mode where incoming controllers drive the selected instrument |
| Orphan | a sample no preset, kit or song refers to |
| Plan | the exact list of operations, shown before any write |
| Preset | a synth sound saved in `SYNTHS` |
| Row | one line of a kit: a sound and its settings |
| Section | a group of clips that play together in a Deluge song |
| Card backup | your full copy of the card, read and never written by everyday work |
| SysEx | MIDI messages specific to a machine; the Deluge's give its version and screen |
| `syncLevel` | the value that locks an LFO, a delay or an arpeggio to the tempo |

# Where the application keeps its files {#fichiers icone=folder}

> Nothing is hidden: here is where everything lives.

| What | Where |
|---|---|
| Settings | `settings.json`, in the configuration folder |
| Index | `library.db`, in the configuration folder |
| Log | `app.log`, in the configuration folder (one MB at most, with the three previous ones beside it: `app.log.1` to `app.log.3`) |
| Backups from the Health page | the folder chosen in the settings; by default `backups`, in the configuration folder |
| Working copy | `%LOCALAPPDATA%\DelugeCompanion\Carte`, unless set otherwise |
| Sync history | `.deluge-companion` in the working copy |
| Originals of audio treatments | `_BACKUP` at the root of the card |
| Archived samples | `_UNUSED` at the root of the card |
| Copies before rewriting | a dated `.bak`, next to each rewritten XML |

The **configuration folder** is `%APPDATA%\DelugeCompanion` under Windows, `~/.config/DelugeCompanion` elsewhere. The `DELUGE_COMPANION_CONFIG` environment variable moves it — and the working copy with it. Settings ▸ About ▸ [Open] shows it in Explorer.

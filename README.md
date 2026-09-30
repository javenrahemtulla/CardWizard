# Card Wizard

Search engine for debate cards. Upload files, it finds each card (tag, cite, body), keeps
which words were highlighted, and lets you search by keyword or by meaning.

## How cards are read

- **Tag**: the line above the cite. Heading 4, bold, or a larger font count as evidence. If the file
  has formatting but the line above a cite has none of it, the card is stored with no tag.
- **Cite**: found by its shape, so it works without styles. Recognised openings: `Author 19 [...]`,
  `Author 26. Bio. "Title"`, `By Name [...]`, `From Org [...]`, `Name is a ...`, `Author, date, "Title"`.
  A URL, bracket, quoted title, or access note is required, so numbered lists and sentences that
  merely start with a year are not mistaken for cites.
- **Body**: everything after the cite until the next tag or heading.
- Three tiers of text, in every file type:
  - **Highlighted**: the words actually spoken. This is what search weighs most.
  - **Underlined / bold**: context around the spoken words. Indexed at lower weight.
  - **Plain**: the rest of the article.

File types: .docx, .doc, .rtf, .odt (via LibreOffice), .pdf, .html, .txt/.md, and pasted text
(Google Docs / Word clipboard keeps highlighting). Plain text and PDFs without highlights have no
spoken/unspoken information.

## Run

    pip install -r requirements.txt
    uvicorn app.main:app --port 8000

Data (SQLite + originals) is stored in `./data` or `$CARDWIZARD_DATA`.
Meaning search needs the BGE-small model (about 100 MB, downloaded on first run, then offline).
If it cannot load, the site falls back to exact-word search and says so.

## Free static site on GitHub Pages

No server. Drag files into the `incoming/` folder on GitHub; a GitHub Action turns them into card data
(`docs/data/`) and publishes `docs/` as a website. Search runs in the visitor's browser.

- One-time: repository **Settings > Pages > Source: GitHub Actions**.
- Add files: open `incoming/` on GitHub, **Add file > Upload files**, commit. Delete a file there to
  remove its cards. The site updates a few minutes later (watch the **Actions** tab).
- Everything is public: the repository, the original files, and the site.
- Not searched in this mode: unread plain text (only tag, cite, highlighted and underlined/bold text).
- Locally: `python tools/build_site.py sync incoming` builds the same data; serve `docs/` with any web server.

## Run on your own computer with a public address

Data stays on your computer (`./data`). A tunnel gives it an `https://` address that anyone with the
password can open while your computer is on and the script is running.

1. Run `./start.sh` (Mac/Linux) or double-click `start.bat` (Windows). Pick a password when asked.
2. Install [Tailscale](https://tailscale.com/download), sign in, then in a terminal run
   `tailscale funnel 8000`. It prints a stable address like `https://your-computer.your-tailnet.ts.net`.
   (Funnel may need to be switched on for your account first; Tailscale prints a link if so.)

Alternatives: `cloudflared tunnel --url http://localhost:8000` (free, no account, but the address
changes every run), or a Cloudflare named tunnel on a domain you own (stable, custom name).

## Deploy

    docker build -t cardwizard .
    docker run -p 8000:8000 -v cardwizard-data:/data -e SITE_PASSWORD=choose-one cardwizard

Any host that runs a container with a persistent volume works (Fly.io, Railway, Render, a VPS).
Mount the volume at `/data`, otherwise the library is lost on redeploy.

**There are no accounts. Anyone with the URL can upload and delete.** Set `SITE_PASSWORD` to require one
shared password (HTTP Basic auth, any username). Do this if the site is public.

## Tests

    pytest

`samples/` (git-ignored) may hold real debate files; tests that use them are skipped when it is empty.

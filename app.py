# IT2025C Week 11 - Week 10's app, ready to go online: a landing page you make yours, and the key in wee.env.
# Run:    python3 app.py      then open http://127.0.0.1:5001
# Needs:  python3 -m pip install -r requirements.txt
# The whole app is in this one file. Your pictures go in the public/ folder.

import base64
import io
import os
import requests
from dotenv import load_dotenv
from flask import Flask, render_template_string, request, jsonify

# ---------- 1. Settings ----------
load_dotenv(os.path.join(os.path.dirname(__file__), "wee.env"))
key = os.environ.get("BEARCAT_KEY", "")

url = "https://apim-azr-ue2-bgpt-prd-ucin.azure-api.net/openai/deployments/gpt-5.4-ptu/chat/completions?api-version=2024-10-21"
NO_ANSWER = "The file does not answer this question."
instructions = (
    "Answer in plain sentences using the provided documents, images, and image metadata. Describe visible image contents when asked, "
    "and use EXIF metadata (including GPS values when present) when relevant.\n"
    "Only if nothing in the provided materials is related to the question, reply with exactly this sentence: " + NO_ANSWER
)


# ---------- 2. Read: any file -> text (Week 9) ----------
def read_any(filename, data):
    """data is the raw bytes of the file. Return the text inside it."""
    name = filename.lower()
    if name.endswith(".pdf"):
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(data))       # treat the bytes as a file
        text = ""
        for page in reader.pages:
            text = text + page.extract_text() + "\n"
        return text
    if name.endswith(".docx"):
        import docx
        document = docx.Document(io.BytesIO(data))
        text = ""
        for paragraph in document.paragraphs:
            text = text + paragraph.text + "\n"
        return text
    return data.decode("utf-8", errors="replace")  # .txt .csv .md: the bytes already are text


def image_media_type(data):
    """Return the supported image media type for known image bytes."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def image_data_url(data, media_type):
    """Encode image bytes in the data URL format expected by the vision API."""
    encoded = base64.b64encode(data).decode("ascii")
    return "data:" + media_type + ";base64," + encoded


def image_exif_text(data):
    """Extract readable top-level, Exif, and GPS metadata from image bytes."""
    from PIL import ExifTags, Image

    with Image.open(io.BytesIO(data)) as image:
        exif = image.getexif()
        if not exif:
            return "No EXIF metadata was found."

        entries = []
        for tag_id, value in exif.items():
            if tag_id not in (ExifTags.IFD.Exif, ExifTags.IFD.GPSInfo):
                tag_name = ExifTags.TAGS.get(tag_id, str(tag_id))
                entries.append(tag_name + ": " + str(value))

        for ifd_name, ifd_id in (("Exif", ExifTags.IFD.Exif), ("GPS", ExifTags.IFD.GPSInfo)):
            tag_names = ExifTags.GPSTAGS if ifd_name == "GPS" else ExifTags.TAGS
            for tag_id, value in exif.get_ifd(ifd_id).items():
                tag_name = tag_names.get(tag_id, str(tag_id))
                if isinstance(value, bytes):
                    value = value.hex()
                entries.append(ifd_name + " " + tag_name + ": " + str(value))

    if not entries:
        return "No EXIF metadata was found."
    return "\n".join(entries)


# ---------- 3. Ask: send the whole text of every file and the question to GPT-5.4 (Week 10) ----------
def ask_files(file_texts, images, prompt):
    """Send document text, image metadata, and image bytes to the model."""
    if key in ("", "PASTE-YOUR-KEY-HERE"):
        return "No key found. Copy .env.example to wee.env and put your key after BEARCAT_KEY="
    context = ""
    for name, text in file_texts:
        context = context + "File: " + name + "\n" + text + "\n\n"
    message_content = [{"type": "text", "text": "Files:\n" + context + "Question: " + prompt}]
    for name, data, media_type in images:
        message_content.append({"type": "text", "text": "Image: " + name})
        message_content.append({
            "type": "image_url",
            "image_url": {"url": image_data_url(data, media_type)}
        })
    payload = {
        "model": "gpt-5.4-ptu",
        "messages": [{"role": "system", "content": instructions}, {"role": "user", "content": message_content}],
        "max_completion_tokens": 2000
    }
    response = requests.post(url, headers={"api-key": key}, json=payload)
    data = response.json() if "json" in response.headers.get("Content-Type", "") else {}   # some errors are not JSON
    if "choices" not in data:
        return "The API said no (status " + str(response.status_code) + "): " + (str(data) if data else response.text[:300])
    return data["choices"][0]["message"]["content"]


# ---------- 4. The web app: three pages and a health check ----------
app = Flask(__name__, static_folder="public", static_url_path="")   # new: public/hero.png is at /hero.png


@app.route("/")
def home():
    return render_template_string(LANDING_PAGE)            # new: the first page people see


@app.route("/start")
def start():
    return render_template_string(INDEX_PAGE)              # the form (it was at / in Week 10)


@app.route("/health")
def health():
    return jsonify({"status": "ok", "message": "Week 11 app is running."})


@app.route("/ask", methods=["POST"])
def ask():
    prompt = request.form.get("prompt", "").strip()
    uploads = [u for u in request.files.getlist("file") if u.filename != ""]   # one or more files
    hex_images = [line.strip() for line in request.form.get("image_hex", "").splitlines() if line.strip()]
    if prompt == "" or (uploads == [] and hex_images == []):
        return render_template_string(RESULT_PAGE, files=[], prompt=prompt,
                                      answer="Choose at least one file and type a question first.")
    file_texts = []
    images = []
    for upload in uploads:
        data = upload.read()
        media_type = image_media_type(data)
        if media_type:
            try:
                file_texts.append(("EXIF metadata for " + upload.filename, image_exif_text(data)))
            except (OSError, ValueError):
                return render_template_string(RESULT_PAGE, files=[u.filename for u in uploads],
                                              prompt=prompt, answer="An uploaded image is damaged or cannot be read. Try another image.")
            images.append((upload.filename, data, media_type))
        elif upload.mimetype.startswith("image/"):
            return render_template_string(RESULT_PAGE, files=[u.filename for u in uploads],
                                          prompt=prompt, answer="An uploaded image is empty, invalid, or in an unsupported format. Use PNG, JPEG, GIF, or WebP.")
        else:
            file_texts.append((upload.filename, read_any(upload.filename, data)))   # bytes -> text
    for index, image_hex in enumerate(hex_images, start=1):
        try:
            data = bytes.fromhex(image_hex)
        except ValueError:
            return render_template_string(RESULT_PAGE, files=[], prompt=prompt,
                                          answer="Hex image " + str(index) + " is invalid. Paste hexadecimal bytes only.")
        media_type = image_media_type(data)
        if not media_type:
            return render_template_string(RESULT_PAGE, files=[], prompt=prompt,
                                          answer="Hex image " + str(index) + " is not a supported PNG, JPEG, GIF, or WebP image.")
        try:
            file_texts.append(("EXIF metadata for Hex image " + str(index), image_exif_text(data)))
        except (OSError, ValueError):
            return render_template_string(RESULT_PAGE, files=[], prompt=prompt,
                                          answer="Hex image " + str(index) + " is damaged or cannot be read.")
        images.append(("Hex image " + str(index), data, media_type))
    file_names = [u.filename for u in uploads] + ["Hex image " + str(index) for index in range(1, len(hex_images) + 1)]
    answer = ask_files(file_texts, images, prompt)           # the model reads every file and image
    return render_template_string(RESULT_PAGE, files=file_names, prompt=prompt, answer=answer)


# ---------- 5. The pages: how they look (STYLE) and what they say ----------
# Change STYLE or a page, save, and refresh the browser.
# Asking BearcatGPT for help? Paste this part. Your key is in wee.env, not here.

STYLE = """
/* Make it yours: change these values first. */
:root {
  --brand: #2b96c0;      /* your project's color: header, buttons, links */
  --page: #f4f5f7;       /* the page background */
  --text: #2f3030;       /* normal text */
  --muted: #6b7280;      /* small, less important text */
}

/* One readable column in the middle of the page */
body {
  font-family: Comic Sans MS, sans-serif;
  color: var(--text);
  background: var(--page);
  max-width: 760px;
  margin: 0 auto;
  padding: 0 16px 40px;
  line-height: 1.5;
}

/* A bar at the top of every page */
.nav { display: flex; gap: 16px; padding: 12px 0; font-weight: bold; }
.nav a { color: var(--brand); text-decoration: none; }

/* The header: the biggest thing on the page says what the app is */
.header {
  background: var(--brand);
  color: white;
  padding: 20px 24px;
  border-radius: 12px;
  margin-bottom: 24px;
}
.header h1 { margin: 0 0 4px; }
.header p { margin: 0; }

/* The picture on the landing page */
.hero { width: 100%; border-radius: 12px; margin-bottom: 24px; display: block; }

/* Cards: a white box groups things that belong together */
.card {
  background: white;
  border-radius: 12px;
  padding: 20px 24px;
  margin-bottom: 24px;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.1);
}
.steps { display: flex; gap: 12px; flex-wrap: wrap; margin: 16px 0; }
.step { flex: 1; min-width: 160px; background: var(--page); border-radius: 10px; padding: 12px 14px; }
label { display: block; font-weight: bold; margin: 12px 0 6px; }
input, textarea { width: 100%; box-sizing: border-box; font: inherit; padding: 8px; }
button, .button {
  display: inline-block;
  margin-top: 16px;
  background: var(--brand);
  color: white;
  border: none;
  border-radius: 8px;
  padding: 10px 20px;
  font: inherit;
  font-weight: bold;
  text-decoration: none;
}
.answer { font-size: 18px; white-space: pre-wrap; border-left: 6px solid var(--brand); }
.note { color: var(--muted); font-size: 14px; }
"""

# The landing page: what the app is, who it is for, and one button to start. Make every line yours.
LANDING_PAGE = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Deep Search</title>
    <style>""" + STYLE + """</style>
  </head>
  <body>
    <nav class="nav"><a href="/">Home</a><a href="/start">Deep Search</a></nav>
    <header class="header">
      <h1>Deep Search</h1>
      <p>Ask a question about your own files and get an answer in plain sentences.</p>
    </header>
    <img class="hero" src="hero.png" alt="A stack of pages and a question bubble">
    <div class="card">
      <h2>Who it is for</h2>
      <p>Anyone who wants to know where an image is from, or know more about pictures.</p>
      <h2>How it works</h2>
      <div class="steps">
        <div class="step"><strong>1. Upload your image</strong><br>One or more images</div>
        <div class="step"><strong>2. Search</strong><br>One question, in plain words.</div>
        <div class="step"><strong>3. Done</strong><br>You will see the results</div>
      </div>
      <a class="button" href="/start">Start</a>
    </div>
    <p class="note">Use fictional or public files only.</p>
  </body>
</html>"""

# The form. The button changes while the model reads your files.
INDEX_PAGE = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Deep Search</title>
    <style>""" + STYLE + """</style>
  </head>
  <body>
    <nav class="nav"><a href="/">Home</a><a href="/start">Deep Search</a></nav>
    <header class="header">
      <h1>Deep Search</h1>
      <p>Upload one or more images and ask one question about them.</p>
    </header>
    <form class="card" action="/ask" method="post" enctype="multipart/form-data"
          onsubmit="this.querySelector('button').textContent = 'Reading your files...';">
      <label for="file">Your images: one or more</label>
      <input type="file" id="file" name="file" accept="image/*" multiple>
      <label for="image_hex">Or paste full image file bytes as hex (one image per line)</label>
      <textarea id="image_hex" name="image_hex" rows="4" placeholder="Hex-encoded PNG, JPEG, GIF, or WebP file bytes"></textarea>
      <label for="prompt">Your question</label>
      <textarea id="prompt" name="prompt" rows="3"></textarea>
      <button type="submit">Ask</button>
    </form>
    <p class="note">Use fictional or public files only.</p>
  </body>
</html>"""

# The answer page. {{ name }} prints a value from Python.
RESULT_PAGE = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Answer</title>
    <style>""" + STYLE + """</style>
  </head>
  <body>
    <nav class="nav"><a href="/">Home</a><a href="/start">Deep Search</a></nav>
    <header class="header">
      <h1>Answer</h1>
      <p><strong>Files:</strong> {{ files|join(", ") }} &middot; <strong>Question:</strong> {{ prompt }}</p>
    </header>
    <div class="card answer">{{ answer }}</div>
    <a class="button" href="/start">Deep Search again</a>
  </body>
</html>"""


if __name__ == "__main__":
    app.run(debug=True, port=5001)   # 5001, not 5000: on a Mac, AirPlay already uses 5000


# ---------- 6. Notes ----------
# The key: copy .env.example to wee.env (Windows: copy .env.example wee.env), then put your key after BEARCAT_KEY=
#   .gitignore keeps wee.env out of Git and GitHub. Check with: git status
#
# Make it yours, on the landing page:
#   --brand in STYLE (your color), the <title> and <h1> (your app's name), the sentence under it,
#   the picture (put yours in public/ and change src="/hero.png"), "Who it is for", and the three steps.
#
# Stuck?
#   No module named ...          -> python3 -m pip install -r requirements.txt
#   No key found                 -> wee.env missing, still the placeholder, or not named BEARCAT_KEY; fix it, then Control+C and run python3 app.py again
#   The API said no (413, 500, or 504) -> your files are too long for one question: try one shorter file
#   The picture does not show    -> is it in public/? Does src="/your-file.png" match the name exactly, capitals too?
#   Address already in use       -> another app (Week 10?) is still running: press Control+C in its terminal
#   Page looks the same after a change -> save app.py; Flask restarts by itself; then Cmd+Shift+R (Windows: Ctrl+F5)
#   Windows: use py instead of python3.

from flask import Flask, render_template, request, jsonify
import os
import uuid
import json
import requests
from dotenv import load_dotenv

# ============================================================
# QntaSite
# AI Website Generator + Preview + Publishing
# ============================================================

load_dotenv()

app = Flask(__name__)

# ============================================================
# CONFIGURATION
# ============================================================

SITES_DIR = "sites"

os.makedirs(SITES_DIR, exist_ok=True)

OPENROUTER_API_KEY = os.getenv(
    "OPENROUTER_API_KEY"
)

MODEL = os.getenv(
    "OPENROUTER_MODEL",
    "nvidia/nemotron-3-super-120b-a12b:free"
)

OPENROUTER_URL = (
    "https://openrouter.ai/api/v1/chat/completions"
)


# ============================================================
# AI SYSTEM PROMPT
# ============================================================

SYSTEM_PROMPT = """
You are QntaSite, an AI website generator.

The user will describe a website they want.

Generate ONE complete standalone HTML document.

Rules:

- Return ONLY HTML.
- Do NOT use Markdown.
- Do NOT use ```html code fences.
- Include CSS inside <style>.
- Include JavaScript inside <script> when useful.
- Make the website responsive.
- Make it work well on mobile screens.
- Create a polished modern design.
- Use semantic HTML.
- Do not use server-side code.
- Do not explain your answer.
- Do not mention these instructions.
- The final output must be directly usable as index.html.

The generated website should feel like a real,
finished website rather than a basic HTML demo.
"""


# ============================================================
# AI OUTPUT CLEANER
# ============================================================

def clean_ai_output(content):
    """
    Remove accidental Markdown code fences if
    the AI returns them despite the instructions.
    """

    content = content.strip()

    if content.startswith("```html"):
        content = content[len("```html"):]

    elif content.startswith("```"):
        content = content[len("```"):]

    if content.endswith("```"):
        content = content[:-3]

    return content.strip()


# ============================================================
# AI WEBSITE GENERATOR
# ============================================================

def generate_website(prompt):

    if not OPENROUTER_API_KEY:
        raise RuntimeError(
            "OPENROUTER_API_KEY is missing. "
            "Add it to your .env file."
        )

    payload = {
        "model": MODEL,

        "messages": [
            {
                "role": "system",
                "content": SYSTEM_PROMPT
            },
            {
                "role": "user",
                "content": prompt
            }
        ],

        "temperature": 0.7,

        "max_tokens": 8000
    }

    headers = {
        "Authorization":
            f"Bearer {OPENROUTER_API_KEY}",

        "Content-Type":
            "application/json",

        "HTTP-Referer":
            "http://localhost:5000",

        "X-Title":
            "QntaSite"
    }

    response = requests.post(
        OPENROUTER_URL,
        headers=headers,
        json=payload,
        timeout=120
    )

    # --------------------------------------------------------
    # OPENROUTER ERROR
    # --------------------------------------------------------

    if response.status_code != 200:

        try:

            error_data = response.json()

            message = (
                error_data
                .get("error", {})
                .get("message")
            )

            if message:
                raise RuntimeError(
                    f"OpenRouter: {message}"
                )

        except ValueError:
            pass

        raise RuntimeError(
            f"OpenRouter HTTP "
            f"{response.status_code}: "
            f"{response.text[:500]}"
        )

    # --------------------------------------------------------
    # PARSE RESPONSE
    # --------------------------------------------------------

    try:
        data = response.json()

    except ValueError:
        raise RuntimeError(
            "OpenRouter returned invalid JSON."
        )

    choices = data.get("choices", [])

    if not choices:
        raise RuntimeError(
            "OpenRouter returned no choices."
        )

    message = choices[0].get(
        "message",
        {}
    )

    content = message.get(
        "content"
    )

    if not content:
        raise RuntimeError(
            "AI returned an empty response."
        )

    return clean_ai_output(content)


# ============================================================
# SITE PATH HELPERS
# ============================================================

def get_site_directory(site_id):

    return os.path.join(
        SITES_DIR,
        site_id
    )


def get_index_path(site_id):

    return os.path.join(
        get_site_directory(site_id),
        "index.html"
    )


def get_metadata_path(site_id):

    return os.path.join(
        get_site_directory(site_id),
        "metadata.json"
    )


# ============================================================
# METADATA
# ============================================================

def load_metadata(site_id):

    metadata_path = get_metadata_path(
        site_id
    )

    if not os.path.isfile(
        metadata_path
    ):
        return {
            "site_id": site_id,
            "published": False
        }

    try:

        with open(
            metadata_path,
            "r",
            encoding="utf-8"
        ) as file:

            metadata = json.load(file)

        return metadata

    except (
        json.JSONDecodeError,
        OSError
    ):

        return {
            "site_id": site_id,
            "published": False
        }


def save_metadata(
    site_id,
    metadata
):

    metadata_path = get_metadata_path(
        site_id
    )

    with open(
        metadata_path,
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            metadata,
            file,
            indent=2
        )


# ============================================================
# HOME
# ============================================================

@app.route("/")
def index():

    return render_template(
        "index.html"
    )


# ============================================================
# GENERATE WEBSITE
# ============================================================

@app.route(
    "/generate",
    methods=["POST"]
)
def generate():

    data = request.get_json(
        silent=True
    ) or {}

    prompt = data.get(
        "prompt",
        ""
    ).strip()

    # --------------------------------------------------------
    # VALIDATION
    # --------------------------------------------------------

    if not prompt:

        return jsonify({
            "success": False,
            "error":
                "Please describe the website you want."
        }), 400

    if len(prompt) > 5000:

        return jsonify({
            "success": False,
            "error":
                "Prompt is too long. "
                "Keep it under 5000 characters."
        }), 400

    # --------------------------------------------------------
    # LOG
    # --------------------------------------------------------

    print()
    print("=" * 60)
    print("QntaSite generation started")
    print("Model:", MODEL)
    print("Prompt:", prompt)
    print("=" * 60)

    # --------------------------------------------------------
    # AI GENERATION
    # --------------------------------------------------------

    try:

        website_html = generate_website(
            prompt
        )

    except Exception as error:

        print()
        print("GENERATION ERROR:")
        print(error)
        print()

        return jsonify({
            "success": False,
            "error": str(error)
        }), 500

    # --------------------------------------------------------
    # CREATE SITE ID
    # --------------------------------------------------------

    site_id = uuid.uuid4().hex[:8]

    site_directory = (
        get_site_directory(site_id)
    )

    os.makedirs(
        site_directory,
        exist_ok=True
    )

    # --------------------------------------------------------
    # SAVE HTML
    # --------------------------------------------------------

    index_path = (
        get_index_path(site_id)
    )

    with open(
        index_path,
        "w",
        encoding="utf-8"
    ) as file:

        file.write(
            website_html
        )

    # --------------------------------------------------------
    # INITIAL METADATA
    # --------------------------------------------------------

    metadata = {
        "site_id": site_id,

        "published": False,

        "prompt": prompt,

        "model": MODEL
    }

    save_metadata(
        site_id,
        metadata
    )

    # --------------------------------------------------------
    # LOG
    # --------------------------------------------------------

    print()
    print("Website generated successfully!")
    print("Site ID:", site_id)
    print("Path:", index_path)
    print("Preview:", f"/site/{site_id}")
    print("Published:", False)
    print()

    # --------------------------------------------------------
    # RESPONSE
    # --------------------------------------------------------

    return jsonify({

        "success": True,

        "site_id":
            site_id,

        "url":
            f"/site/{site_id}",

        "published_url":
            f"/p/{site_id}",

        "published":
            False
    })


# ============================================================
# PREVIEW GENERATED WEBSITE
# ============================================================

@app.route(
    "/site/<site_id>"
)
def view_site(site_id):

    index_path = (
        get_index_path(site_id)
    )

    if not os.path.isfile(
        index_path
    ):

        return (
            "Site not found",
            404
        )

    with open(
        index_path,
        "r",
        encoding="utf-8"
    ) as file:

        website = file.read()

    return website


# ============================================================
# PUBLISH WEBSITE
# ============================================================

@app.route(
    "/publish",
    methods=["POST"]
)
def publish():

    data = request.get_json(
        silent=True
    ) or {}

    site_id = data.get(
        "site_id",
        ""
    ).strip()

    # --------------------------------------------------------
    # VALIDATION
    # --------------------------------------------------------

    if not site_id:

        return jsonify({
            "success": False,
            "error":
                "Missing site ID."
        }), 400

    index_path = (
        get_index_path(site_id)
    )

    # --------------------------------------------------------
    # CHECK WEBSITE
    # --------------------------------------------------------

    if not os.path.isfile(
        index_path
    ):

        return jsonify({
            "success": False,
            "error":
                "Website not found."
        }), 404

    # --------------------------------------------------------
    # LOAD EXISTING METADATA
    # --------------------------------------------------------

    metadata = load_metadata(
        site_id
    )

    # --------------------------------------------------------
    # PUBLISH
    # --------------------------------------------------------

    metadata["site_id"] = site_id

    metadata["published"] = True

    save_metadata(
        site_id,
        metadata
    )

    # --------------------------------------------------------
    # LOG
    # --------------------------------------------------------

    print()
    print("=" * 60)
    print("WEBSITE PUBLISHED")
    print("Site ID:", site_id)
    print(
        "URL:",
        f"/p/{site_id}"
    )
    print("=" * 60)
    print()

    # --------------------------------------------------------
    # RESPONSE
    # --------------------------------------------------------

    return jsonify({

        "success":
            True,

        "site_id":
            site_id,

        "url":
            f"/p/{site_id}",

        "published":
            True
    })


# ============================================================
# PUBLISHED WEBSITE
# ============================================================

@app.route(
    "/p/<site_id>"
)
def published_site(site_id):

    index_path = (
        get_index_path(site_id)
    )

    # --------------------------------------------------------
    # WEBSITE EXISTS?
    # --------------------------------------------------------

    if not os.path.isfile(
        index_path
    ):

        return (
            "Published website not found.",
            404
        )

    # --------------------------------------------------------
    # CHECK PUBLISH STATE
    # --------------------------------------------------------

    metadata = load_metadata(
        site_id
    )

    if not metadata.get(
        "published",
        False
    ):

        return (
            """
            <!DOCTYPE html>
            <html>
            <head>
                <title>Not Published</title>
                <meta
                    name="viewport"
                    content="width=device-width,
                             initial-scale=1.0"
                >
                <style>
                    body {
                        margin: 0;
                        min-height: 100vh;
                        display: grid;
                        place-items: center;
                        background: #08090d;
                        color: white;
                        font-family: system-ui;
                        text-align: center;
                        padding: 20px;
                    }

                    .box {
                        max-width: 500px;
                    }

                    h1 {
                        font-size: 32px;
                    }

                    p {
                        color: #929aaa;
                    }
                </style>
            </head>

            <body>

                <div class="box">

                    <h1>
                        Website not published
                    </h1>

                    <p>
                        This website exists,
                        but it has not been
                        published yet.
                    </p>

                </div>

            </body>
            </html>
            """,
            403
        )

    # --------------------------------------------------------
    # SERVE WEBSITE
    # --------------------------------------------------------

    with open(
        index_path,
        "r",
        encoding="utf-8"
    ) as file:

        website = file.read()

    return website


# ============================================================
# SITE STATUS
# ============================================================

@app.route(
    "/api/site/<site_id>"
)
def site_status(site_id):

    index_path = (
        get_index_path(site_id)
    )

    if not os.path.isfile(
        index_path
    ):

        return jsonify({
            "success": False,
            "error":
                "Site not found."
        }), 404

    metadata = load_metadata(
        site_id
    )

    return jsonify({

        "success":
            True,

        "site_id":
            site_id,

        "published":
            metadata.get(
                "published",
                False
            ),

        "preview_url":
            f"/site/{site_id}",

        "published_url":
            f"/p/{site_id}"
    })


# ============================================================
# HEALTH
# ============================================================

@app.route(
    "/health"
)
def health():

    return jsonify({

        "status":
            "ok",

        "service":
            "QntaSite",

        "ai_configured":
            bool(
                OPENROUTER_API_KEY
            ),

        "model":
            MODEL,

        "storage":
            SITES_DIR
    })


# ============================================================
# ERROR HANDLERS
# ============================================================

@app.errorhandler(404)
def not_found(error):

    return jsonify({

        "success":
            False,

        "error":
            "Route not found."
    }), 404


@app.errorhandler(500)
def internal_error(error):

    return jsonify({

        "success":
            False,

        "error":
            "Internal server error."
    }), 500


# ============================================================
# START SERVER
# ============================================================

if __name__ == "__main__":

    print()
    print("=" * 60)
    print("QntaSite")
    print("AI Website Generator")
    print("=" * 60)
    print()
    print("Model:", MODEL)
    print(
        "AI configured:",
        bool(OPENROUTER_API_KEY)
    )
    print()
    print(
        "Local URL:",
        "http://127.0.0.1:5000"
    )
    print()
    print("=" * 60)
    print()

    app.run(
        host="0.0.0.0",
        port=5000,
        debug=True
    )

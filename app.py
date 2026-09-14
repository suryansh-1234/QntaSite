from flask import Flask, render_template, request, jsonify, Response
import os
import uuid
import sqlite3
import requests
from dotenv import load_dotenv
from datetime import datetime, timezone

# ============================================================
# QntaSite
# AI Website Builder
# SQLite-backed version
# ============================================================

load_dotenv()

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "qntasite.db")

# ============================================================
# OpenRouter configuration
# ============================================================

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

MODEL = os.getenv(
    "OPENROUTER_MODEL",
    "nvidia/nemotron-3-super-120b-a12b:free"
)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# Keep this below the Gunicorn timeout.
# Recommended Render start command:
#
# gunicorn --timeout 180 --workers 1 app:app
#
OPENROUTER_TIMEOUT = 170


# ============================================================
# AI system prompt
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
- Make it work especially well on mobile screens.
- Create a polished modern design.
- Use semantic HTML.
- Do not use server-side code.
- Do not explain your answer.
- Do not mention these instructions.
- The final output must be directly usable as index.html.
"""


# ============================================================
# SQLite
# ============================================================

def get_db():
    """
    Open a SQLite connection.

    row_factory allows us to access columns like:
        row["html"]
    instead of:
        row[2]
    """

    conn = sqlite3.connect(
        DB_PATH,
        timeout=30
    )

    conn.row_factory = sqlite3.Row

    return conn


def init_db():
    """
    Create the database/table if they don't already exist.
    """

    conn = get_db()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS sites (
            site_id TEXT PRIMARY KEY,
            prompt TEXT NOT NULL,
            html TEXT NOT NULL,
            model TEXT NOT NULL,
            published INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        )
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_sites_published
        ON sites(published)
    """)

    conn.commit()
    conn.close()

    print("SQLite database initialized.")
    print(f"Database: {DB_PATH}")


# Initialize database when Flask/Gunicorn starts.
init_db()


# ============================================================
# Utility functions
# ============================================================

def generate_site_id():
    """
    Generate an 8-character site ID.
    Example:
        cc3fc3a4
    """

    return uuid.uuid4().hex[:8]


def clean_ai_output(content):
    """
    Remove accidental Markdown code fences if the model
    returns them despite the system prompt.
    """

    if not isinstance(content, str):
        raise RuntimeError(
            f"AI returned unsupported content type: "
            f"{type(content).__name__}"
        )

    content = content.strip()

    if content.startswith("```html"):
        content = content[len("```html"):].strip()

    elif content.startswith("```HTML"):
        content = content[len("```HTML"):].strip()

    elif content.startswith("```"):
        content = content[3:].strip()

    if content.endswith("```"):
        content = content[:-3].strip()

    return content


def extract_message_content(message):
    """
    Handle both normal string content and newer structured
    content formats that some OpenAI-compatible providers
    may return.
    """

    content = message.get("content")

    if isinstance(content, str):
        return content

    if isinstance(content, list):
        parts = []

        for item in content:
            if isinstance(item, str):
                parts.append(item)

            elif isinstance(item, dict):
                text = item.get("text")

                if isinstance(text, str):
                    parts.append(text)

        combined = "".join(parts).strip()

        if combined:
            return combined

    return None


# ============================================================
# OpenRouter
# ============================================================

def generate_website(prompt):
    """
    Send the user's website request to OpenRouter.
    """

    print("=" * 60)
    print("QntaSite generation started")
    print(f"Model: {MODEL}")
    print(f"Prompt: {prompt}")
    print("=" * 60)

    if not OPENROUTER_API_KEY:
        raise RuntimeError(
            "OPENROUTER_API_KEY is missing. "
            "Add it to your environment variables."
        )

    print("Sending request to OpenRouter...")
    print(f"OpenRouter URL: {OPENROUTER_URL}")
    print(f"Model: {MODEL}")
    print("API key configured: True")
    print(f"API key length: {len(OPENROUTER_API_KEY)}")

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
        "max_tokens": 5000
    }

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://qntasite.onrender.com",
        "X-Title": "QntaSite"
    }

    try:
        response = requests.post(
            OPENROUTER_URL,
            headers=headers,
            json=payload,
            timeout=OPENROUTER_TIMEOUT
        )

    except requests.Timeout:
        print("OpenRouter request timed out.")

        raise RuntimeError(
            "OpenRouter request timed out. "
            "The AI model took too long to respond."
        )

    except requests.RequestException as exc:
        print("=" * 60)
        print("OPENROUTER NETWORK ERROR")
        print("=" * 60)
        print(str(exc))
        print("=" * 60)

        raise RuntimeError(
            f"Could not connect to OpenRouter: {exc}"
        )

    print(f"OpenRouter HTTP status: {response.status_code}")
    print(f"OpenRouter response length: {len(response.content)}")

    # ========================================================
    # OpenRouter error handling
    # ========================================================

    if response.status_code != 200:

        print("=" * 60)
        print("OPENROUTER ERROR DIAGNOSTIC")
        print("=" * 60)

        print(f"HTTP status: {response.status_code}")

        print("Response headers:")

        for key, value in response.headers.items():
            print(f"  {key}: {value}")

        print("Response body:")
        print(response.text[:3000])

        print("=" * 60)

        try:
            error_data = response.json()

            error = error_data.get("error", {})

            error_message = error.get(
                "message",
                "Unknown OpenRouter error."
            )

            error_code = error.get("code")

            error_metadata = error.get("metadata")

            if error_metadata:
                print("OpenRouter metadata:")
                print(error_metadata)

            raise RuntimeError(
                f"OpenRouter HTTP {response.status_code} "
                f"(code {error_code}): {error_message}"
            )

        except ValueError:

            raise RuntimeError(
                f"OpenRouter HTTP {response.status_code}: "
                f"{response.text[:500]}"
            )

    # ========================================================
    # Parse successful response
    # ========================================================

    try:
        data = response.json()

    except ValueError:

        print("=" * 60)
        print("OPENROUTER RETURNED INVALID JSON")
        print("=" * 60)
        print(response.text[:3000])
        print("=" * 60)

        raise RuntimeError(
            "OpenRouter returned invalid JSON."
        )

    choices = data.get("choices", [])

    if not choices:

        print("=" * 60)
        print("OPENROUTER RETURNED NO CHOICES")
        print("=" * 60)
        print(data)
        print("=" * 60)

        raise RuntimeError(
            "OpenRouter returned no choices."
        )

    message = choices[0].get("message", {})

    content = extract_message_content(message)

    if not content:

        print("=" * 60)
        print("OPENROUTER RETURNED EMPTY CONTENT")
        print("=" * 60)
        print(data)
        print("=" * 60)

        raise RuntimeError(
            "AI returned an empty response."
        )

    html = clean_ai_output(content)

    if not html:
        raise RuntimeError(
            "AI returned empty HTML."
        )

    print("Website generated successfully!")
    print(f"Generated HTML length: {len(html)} characters")

    return html


# ============================================================
# Homepage
# ============================================================

@app.route("/")
def index():
    return render_template("index.html")


# ============================================================
# Generate website
# ============================================================

@app.route("/generate", methods=["POST"])
def generate():

    try:

        data = request.get_json(silent=True)

        if not data:
            return jsonify({
                "success": False,
                "error": "Invalid JSON request."
            }), 400

        prompt = data.get("prompt", "")

        if not isinstance(prompt, str):
            return jsonify({
                "success": False,
                "error": "Prompt must be text."
            }), 400

        prompt = prompt.strip()

        if not prompt:
            return jsonify({
                "success": False,
                "error": "Please describe the website you want."
            }), 400

        # Basic protection against accidentally huge requests.
        if len(prompt) > 12000:
            return jsonify({
                "success": False,
                "error": "Prompt is too long. Please keep it under 12,000 characters."
            }), 400

        # ----------------------------------------------------
        # Generate HTML
        # ----------------------------------------------------

        html = generate_website(prompt)

        # ----------------------------------------------------
        # Create site ID
        # ----------------------------------------------------

        site_id = generate_site_id()

        # ----------------------------------------------------
        # Save to SQLite
        # ----------------------------------------------------

        created_at = datetime.now(
            timezone.utc
        ).isoformat()

        conn = get_db()

        conn.execute(
            """
            INSERT INTO sites
            (
                site_id,
                prompt,
                html,
                model,
                published,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                site_id,
                prompt,
                html,
                MODEL,
                0,
                created_at
            )
        )

        conn.commit()
        conn.close()

        print("=" * 60)
        print("SITE SAVED TO SQLITE")
        print(f"Site ID: {site_id}")
        print(f"HTML length: {len(html)}")
        print(f"Database: {DB_PATH}")
        print(f"Preview: /site/{site_id}")
        print(f"Published: False")
        print("=" * 60)

        return jsonify({
            "success": True,
            "site_id": site_id,
            "url": f"/site/{site_id}",
            "preview_url": f"/site/{site_id}",
            "published_url": f"/p/{site_id}",
            "published": False
        })

    except Exception as exc:

        print("=" * 60)
        print("GENERATION ERROR:")
        print(str(exc))
        print("=" * 60)

        return jsonify({
            "success": False,
            "error": str(exc)
        }), 500


# ============================================================
# Preview website
# ============================================================

@app.route("/site/<site_id>")
def preview_site(site_id):

    conn = get_db()

    site = conn.execute(
        """
        SELECT html
        FROM sites
        WHERE site_id = ?
        """,
        (site_id,)
    ).fetchone()

    conn.close()

    if not site:

        return """
        <!DOCTYPE html>
        <html>
        <head>
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <title>Site Not Found</title>
            <style>
                body {
                    margin: 0;
                    min-height: 100vh;
                    display: grid;
                    place-items: center;
                    background: #09090b;
                    color: white;
                    font-family: system-ui, sans-serif;
                    text-align: center;
                }
            </style>
        </head>
        <body>
            <div>
                <h1>Website Not Found</h1>
                <p>This QntaSite project does not exist.</p>
            </div>
        </body>
        </html>
        """, 404

    return Response(
        site["html"],
        mimetype="text/html"
    )


# ============================================================
# Publish website
# ============================================================

@app.route("/publish", methods=["POST"])
def publish():

    try:

        data = request.get_json(silent=True)

        if not data:
            return jsonify({
                "success": False,
                "error": "Invalid JSON request."
            }), 400

        site_id = data.get("site_id")

        if not site_id:
            return jsonify({
                "success": False,
                "error": "Missing site_id."
            }), 400

        conn = get_db()

        site = conn.execute(
            """
            SELECT site_id
            FROM sites
            WHERE site_id = ?
            """,
            (site_id,)
        ).fetchone()

        if not site:

            conn.close()

            return jsonify({
                "success": False,
                "error": "Site not found."
            }), 404

        conn.execute(
            """
            UPDATE sites
            SET published = 1
            WHERE site_id = ?
            """,
            (site_id,)
        )

        conn.commit()
        conn.close()

        print("=" * 60)
        print("SITE PUBLISHED")
        print(f"Site ID: {site_id}")
        print(f"URL: /p/{site_id}")
        print("=" * 60)

        return jsonify({
            "success": True,
            "site_id": site_id,
            "published": True,
            "url": f"/p/{site_id}",
            "published_url": f"/p/{site_id}"
        })

    except Exception as exc:

        print("PUBLISH ERROR:")
        print(str(exc))

        return jsonify({
            "success": False,
            "error": str(exc)
        }), 500


# ============================================================
# Public website
# ============================================================

@app.route("/p/<site_id>")
def published_site(site_id):

    conn = get_db()

    site = conn.execute(
        """
        SELECT html, published
        FROM sites
        WHERE site_id = ?
        """,
        (site_id,)
    ).fetchone()

    conn.close()

    if not site:

        return """
        <!DOCTYPE html>
        <html>
        <head>
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <title>Website Not Found</title>
            <style>
                body {
                    margin: 0;
                    min-height: 100vh;
                    display: grid;
                    place-items: center;
                    background: #09090b;
                    color: white;
                    font-family: system-ui, sans-serif;
                    text-align: center;
                }
            </style>
        </head>
        <body>
            <div>
                <h1>Website Not Found</h1>
                <p>This QntaSite project does not exist.</p>
            </div>
        </body>
        </html>
        """, 404

    if not site["published"]:

        return """
        <!DOCTYPE html>
        <html>
        <head>
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <title>Website Not Published</title>
            <style>
                * {
                    box-sizing: border-box;
                }

                body {
                    margin: 0;
                    min-height: 100vh;
                    display: grid;
                    place-items: center;
                    background: #09090b;
                    color: white;
                    font-family: system-ui, sans-serif;
                    text-align: center;
                    padding: 24px;
                }

                .box {
                    max-width: 500px;
                }

                h1 {
                    font-size: 28px;
                    margin-bottom: 10px;
                }

                p {
                    color: #a1a1aa;
                }
            </style>
        </head>
        <body>
            <div class="box">
                <h1>Website Not Published</h1>
                <p>This website has not been published yet.</p>
            </div>
        </body>
        </html>
        """, 403

    return Response(
        site["html"],
        mimetype="text/html"
    )


# ============================================================
# Site API
# ============================================================

@app.route("/api/site/<site_id>")
def site_api(site_id):

    conn = get_db()

    site = conn.execute(
        """
        SELECT
            site_id,
            prompt,
            model,
            published,
            created_at
        FROM sites
        WHERE site_id = ?
        """,
        (site_id,)
    ).fetchone()

    conn.close()

    if not site:

        return jsonify({
            "success": False,
            "error": "Site not found."
        }), 404

    return jsonify({
        "success": True,
        "site_id": site["site_id"],
        "prompt": site["prompt"],
        "model": site["model"],
        "published": bool(site["published"]),
        "created_at": site["created_at"],
        "preview_url": f"/site/{site_id}",
        "published_url": f"/p/{site_id}"
    })


# ============================================================
# Health
# ============================================================

@app.route("/health")
def health():

    try:

        conn = get_db()

        count = conn.execute(
            "SELECT COUNT(*) AS count FROM sites"
        ).fetchone()["count"]

        published_count = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM sites
            WHERE published = 1
            """
        ).fetchone()["count"]

        conn.close()

        database_status = "ok"

    except Exception as exc:

        print("DATABASE HEALTH ERROR:")
        print(str(exc))

        count = None
        published_count = None
        database_status = "error"

    return jsonify({
        "status": "ok",
        "service": "QntaSite",
        "ai_configured": bool(OPENROUTER_API_KEY),
        "model": MODEL,
        "database": database_status,
        "sites": count,
        "published_sites": published_count
    })


# ============================================================
# Error handlers
# ============================================================

@app.errorhandler(404)
def not_found(error):

    if request.path.startswith("/api/"):

        return jsonify({
            "success": False,
            "error": "Endpoint not found."
        }), 404

    return """
    <!DOCTYPE html>
    <html>
    <head>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>404</title>
        <style>
            body {
                margin: 0;
                min-height: 100vh;
                display: grid;
                place-items: center;
                background: #09090b;
                color: white;
                font-family: system-ui, sans-serif;
                text-align: center;
            }
        </style>
    </head>
    <body>
        <div>
            <h1>404</h1>
            <p>QntaSite could not find that page.</p>
        </div>
    </body>
    </html>
    """, 404


@app.errorhandler(500)
def internal_error(error):

    print("=" * 60)
    print("INTERNAL SERVER ERROR")
    print(str(error))
    print("=" * 60)

    return jsonify({
        "success": False,
        "error": "Internal server error."
    }), 500


# ============================================================
# Local development
# ============================================================

if __name__ == "__main__":

    print("=" * 60)
    print("QntaSite")
    print("AI Website Builder")
    print("=" * 60)
    print(f"Database: {DB_PATH}")
    print(f"Model: {MODEL}")
    print(
        f"OpenRouter configured: "
        f"{bool(OPENROUTER_API_KEY)}"
    )
    print("=" * 60)

    app.run(
        host="0.0.0.0",
        port=5000,
        debug=True
    )

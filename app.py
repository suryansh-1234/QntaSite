from flask import Flask, render_template, request, jsonify
import os
import uuid
import json
import requests
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

SITES_DIR = "sites"
os.makedirs(SITES_DIR, exist_ok=True)

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

MODEL = os.getenv(
    "OPENROUTER_MODEL",
    "nvidia/nemotron-3-super-120b-a12b:free"
)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

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
"""


def clean_ai_output(content):
    content = content.strip()

    if content.startswith("```html"):
        content = content[len("```html"):]

    elif content.startswith("```"):
        content = content[len("```"):]

    if content.endswith("```"):
        content = content[:-3]

    return content.strip()


def generate_website(prompt):
    if not OPENROUTER_API_KEY:
        raise RuntimeError(
            "OPENROUTER_API_KEY is missing. "
            "Add it to your Render environment variables."
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
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://qntasite.onrender.com",
        "X-Title": "QntaSite"
    }

    print()
    print("Sending request to OpenRouter...")
    print("OpenRouter URL:", OPENROUTER_URL)
    print("Model:", MODEL)
    print("API key configured:", bool(OPENROUTER_API_KEY))
    print("API key length:", len(OPENROUTER_API_KEY))
    print()

    try:
        response = requests.post(
            OPENROUTER_URL,
            headers=headers,
            json=payload,
            timeout=120
        )

    except requests.RequestException as error:
        raise RuntimeError(
            f"Network error while contacting OpenRouter: {error}"
        )

    print("OpenRouter HTTP status:", response.status_code)
    print("OpenRouter response length:", len(response.text))

    if response.status_code != 200:

        print()
        print("========== OPENROUTER ERROR DIAGNOSTIC ==========")
        print("HTTP status:", response.status_code)
        print("Response headers:")

        for key, value in response.headers.items():
            print(f"  {key}: {value}")

        print()
        print("Response body:")
        print(response.text[:2000])
        print("=================================================")
        print()

        try:
            error_data = response.json()
            error_info = error_data.get("error", {})

            code = error_info.get(
                "code",
                response.status_code
            )

            message = error_info.get(
                "message",
                "Unknown OpenRouter error"
            )

            metadata = error_info.get(
                "metadata"
            )

            diagnostic = (
                f"OpenRouter HTTP {response.status_code} "
                f"(code {code}): {message}"
            )

            if metadata:
                diagnostic += f" | metadata: {metadata}"

            raise RuntimeError(diagnostic)

        except ValueError:
            raise RuntimeError(
                f"OpenRouter HTTP {response.status_code}: "
                f"{response.text[:1000]}"
            )

    try:
        data = response.json()

    except ValueError:
        raise RuntimeError(
            "OpenRouter returned invalid JSON."
        )

    choices = data.get("choices", [])

    if not choices:
        print()
        print("========== EMPTY CHOICES DIAGNOSTIC ==========")
        print(json.dumps(data, indent=2)[:5000])
        print("==============================================")
        print()

        raise RuntimeError(
            "OpenRouter returned no choices."
        )

    message = choices[0].get("message", {})
    content = message.get("content")

    if not content:
        print()
        print("========== EMPTY CONTENT DIAGNOSTIC ==========")
        print(json.dumps(data, indent=2)[:5000])
        print("==============================================")
        print()

        raise RuntimeError(
            "AI returned an empty response."
        )

    print("OpenRouter response received successfully.")
    print("Generated characters:", len(content))

    return clean_ai_output(content)


def get_site_directory(site_id):
    return os.path.join(SITES_DIR, site_id)


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


def load_metadata(site_id):
    metadata_path = get_metadata_path(site_id)

    if not os.path.isfile(metadata_path):
        return {}

    try:
        with open(
            metadata_path,
            "r",
            encoding="utf-8"
        ) as file:
            return json.load(file)

    except (OSError, json.JSONDecodeError):
        return {}


def save_metadata(site_id, metadata):
    metadata_path = get_metadata_path(site_id)

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


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/generate", methods=["POST"])
def generate():
    data = request.get_json(silent=True) or {}

    prompt = data.get(
        "prompt",
        ""
    ).strip()

    if not prompt:
        return jsonify({
            "success": False,
            "error": "Please describe the website you want."
        }), 400

    if len(prompt) > 5000:
        return jsonify({
            "success": False,
            "error": (
                "Prompt is too long. "
                "Keep it under 5000 characters."
            )
        }), 400

    print()
    print("=" * 60)
    print("QntaSite generation started")
    print("Model:", MODEL)
    print("Prompt:", prompt)
    print("=" * 60)

    try:
        website_html = generate_website(prompt)

    except Exception as error:
        print()
        print("GENERATION ERROR:")
        print(error)
        print()

        return jsonify({
            "success": False,
            "error": str(error)
        }), 500

    site_id = uuid.uuid4().hex[:8]

    site_directory = get_site_directory(
        site_id
    )

    os.makedirs(
        site_directory,
        exist_ok=True
    )

    index_path = get_index_path(
        site_id
    )

    with open(
        index_path,
        "w",
        encoding="utf-8"
    ) as file:
        file.write(website_html)

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

    print()
    print("Website generated successfully!")
    print("Site ID:", site_id)
    print("Path:", index_path)
    print("Preview:", f"/site/{site_id}")
    print("Published:", False)
    print()

    return jsonify({
        "success": True,
        "site_id": site_id,
        "url": f"/site/{site_id}",
        "preview_url": f"/site/{site_id}",
        "published_url": f"/p/{site_id}"
    })


@app.route("/site/<site_id>")
def view_site(site_id):
    site_path = get_index_path(
        site_id
    )

    if not os.path.isfile(site_path):
        return "Site not found", 404

    with open(
        site_path,
        "r",
        encoding="utf-8"
    ) as file:
        website = file.read()

    return website


@app.route("/publish", methods=["POST"])
def publish():
    data = request.get_json(silent=True) or {}

    site_id = data.get(
        "site_id",
        ""
    ).strip()

    if not site_id:
        return jsonify({
            "success": False,
            "error": "Missing site ID."
        }), 400

    index_path = get_index_path(
        site_id
    )

    if not os.path.isfile(index_path):
        return jsonify({
            "success": False,
            "error": "Site not found."
        }), 404

    metadata = load_metadata(
        site_id
    )

    metadata["site_id"] = site_id
    metadata["published"] = True

    save_metadata(
        site_id,
        metadata
    )

    print()
    print("=" * 60)
    print("WEBSITE PUBLISHED")
    print("Site ID:", site_id)
    print("URL:", f"/p/{site_id}")
    print("=" * 60)
    print()

    return jsonify({
        "success": True,
        "site_id": site_id,
        "url": f"/p/{site_id}"
    })


@app.route("/p/<site_id>")
def published_site(site_id):
    metadata = load_metadata(
        site_id
    )

    if not metadata.get(
        "published",
        False
    ):
        return """
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <title>Website Not Published</title>
            <style>
                body {
                    margin: 0;
                    min-height: 100vh;
                    display: grid;
                    place-items: center;
                    font-family: system-ui, sans-serif;
                    background: #0b0b0f;
                    color: white;
                }

                .box {
                    text-align: center;
                    padding: 40px;
                }

                h1 {
                    margin-bottom: 10px;
                }

                p {
                    color: #999;
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

    site_path = get_index_path(
        site_id
    )

    if not os.path.isfile(site_path):
        return "Site not found", 404

    with open(
        site_path,
        "r",
        encoding="utf-8"
    ) as file:
        website = file.read()

    return website


@app.route("/api/site/<site_id>")
def site_api(site_id):
    metadata = load_metadata(
        site_id
    )

    if not metadata:
        return jsonify({
            "success": False,
            "error": "Site not found."
        }), 404

    return jsonify({
        "success": True,
        "site_id": site_id,
        "published": metadata.get(
            "published",
            False
        ),
        "preview_url": f"/site/{site_id}",
        "published_url": f"/p/{site_id}"
    })


@app.route("/health")
def health():
    return jsonify({
        "status": "ok",
        "service": "QntaSite",
        "ai_configured": bool(
            OPENROUTER_API_KEY
        ),
        "model": MODEL
    })


@app.errorhandler(404)
def not_found(error):
    return jsonify({
        "success": False,
        "error": "Route not found."
    }), 404


@app.errorhandler(500)
def server_error(error):
    return jsonify({
        "success": False,
        "error": "Internal server error."
    }), 500


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
    print("Local URL: http://127.0.0.1:5000")
    print()
    print("=" * 60)
    print()

    app.run(
        host="0.0.0.0",
        port=5000,
        debug=True
    )

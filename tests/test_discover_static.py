import json
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_discover_marker_popup_uses_dom_text_content():
    payload = '</a><img src=x onerror="globalThis.__xss=1">'
    script = f"""
    const fs = require("fs");
    const code = fs.readFileSync("app/static/js/discover.js", "utf8");
    let popupContent;
    global.window = {{
      __discover: {{
        markers: [{{ lat: 45, lon: -75, title: {json.dumps(payload)}, url: "/rides/1" }}],
        bbox: null,
        center: [45, -75]
      }}
    }};
    global.document = {{
      getElementById: (id) => id === "map" ? {{}} : null,
      createElement: (tagName) => ({{
        tagName: tagName.toUpperCase(),
        href: "",
        textContent: ""
      }})
    }};
    global.L = {{
      map: () => ({{ fitBounds() {{}}, setView() {{}} }}),
      tileLayer: () => ({{ addTo() {{}} }}),
      marker: () => ({{
        addTo() {{ return this; }},
        bindPopup(content) {{ popupContent = content; }}
      }})
    }};
    eval(code);
    if (typeof popupContent === "string") {{
      throw new Error("popup content must not be an HTML string");
    }}
    if (popupContent.tagName !== "A") {{
      throw new Error(`expected anchor popup content, got ${{popupContent.tagName}}`);
    }}
    if (popupContent.textContent !== {json.dumps(payload)}) {{
      throw new Error("marker title was not assigned as textContent");
    }}
    if (popupContent.href !== "/rides/1") {{
      throw new Error(`unexpected popup href: ${{popupContent.href}}`);
    }}
    """

    subprocess.run(["node", "-e", textwrap.dedent(script)], check=True, cwd=Path.cwd())

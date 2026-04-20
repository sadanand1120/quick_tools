import html
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse


HTML_PAGE = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>__TITLE_HTML__</title>
    <style>
      html,
      body {
        margin: 0;
        height: 100%;
        overflow: hidden;
        background: #050505;
        color: #f4f4f4;
        font-family: sans-serif;
      }

      #app {
        width: 100%;
        height: 100%;
      }

      #status {
        position: fixed;
        top: 12px;
        left: 12px;
        z-index: 10;
        padding: 10px 12px;
        border-radius: 8px;
        background: rgba(0, 0, 0, 0.68);
        font-size: 14px;
        line-height: 1.4;
        pointer-events: none;
      }
    </style>
    <script type="importmap">
      {
        "imports": {
          "three": "https://unpkg.com/three@0.166.1/build/three.module.js",
          "three/addons/": "https://unpkg.com/three@0.166.1/examples/jsm/"
        }
      }
    </script>
  </head>
  <body>
    <div id="status">Loading __TITLE_HTML__...</div>
    <div id="app"></div>
    <script type="module">
      import * as THREE from "three";
      import { OrbitControls } from "three/addons/controls/OrbitControls.js";
      import { PLYLoader } from "three/addons/loaders/PLYLoader.js";

      const container = document.getElementById("app");
      const status = document.getElementById("status");
      const title = __TITLE_JS__;

      const renderer = new THREE.WebGLRenderer({ antialias: true });
      renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
      renderer.setSize(window.innerWidth, window.innerHeight);
      renderer.outputColorSpace = THREE.SRGBColorSpace;
      container.appendChild(renderer.domElement);

      const scene = new THREE.Scene();
      scene.background = new THREE.Color(0x050505);

      const camera = new THREE.PerspectiveCamera(
        55,
        window.innerWidth / window.innerHeight,
        0.01,
        1e6,
      );
      camera.up.set(0, 0, 1);
      camera.position.set(2, 2, 1.5);

      const controls = new OrbitControls(camera, renderer.domElement);
      controls.enableDamping = true;

      const loader = new PLYLoader();

      function formatBytes(bytes) {
        if (!bytes || bytes < 0) return "";
        const units = ["B", "KB", "MB", "GB"];
        let value = bytes;
        let unit = 0;
        while (value >= 1024 && unit < units.length - 1) {
          value /= 1024;
          unit += 1;
        }
        return `${value.toFixed(unit === 0 ? 0 : 1)} ${units[unit]}`;
      }

      loader.load(
        "/data.ply",
        (geometry) => {
          if (geometry.hasAttribute("normal")) {
            geometry.deleteAttribute("normal");
          }

          geometry.center();
          geometry.computeBoundingSphere();

          const radius = geometry.boundingSphere?.radius || 1;
          const material = new THREE.PointsMaterial({
            size: Math.max(radius / 400, 0.0025),
            sizeAttenuation: true,
            vertexColors: geometry.hasAttribute("color"),
          });

          const cloud = new THREE.Points(geometry, material);
          scene.add(cloud);

          camera.near = Math.max(radius / 1000, 0.001);
          camera.far = radius * 20;
          camera.position.set(radius * 1.7, -radius * 1.7, radius * 1.1);
          camera.updateProjectionMatrix();
          controls.target.set(0, 0, 0);
          controls.update();

          const count = geometry.getAttribute("position").count.toLocaleString();
          status.innerHTML = `${count} points<br />Drag to orbit, scroll to zoom`;
        },
        (event) => {
          const loaded = formatBytes(event.loaded);
          const total = formatBytes(event.total);
          status.textContent = total
            ? `Loading ${title}... ${loaded} / ${total}`
            : `Loading ${title}... ${loaded}`;
        },
        (error) => {
          console.error(error);
          status.textContent = `Failed to load ${title}: ${error?.message || error}`;
        },
      );

      window.addEventListener("resize", () => {
        camera.aspect = window.innerWidth / window.innerHeight;
        camera.updateProjectionMatrix();
        renderer.setSize(window.innerWidth, window.innerHeight);
      });

      function animate() {
        requestAnimationFrame(animate);
        controls.update();
        renderer.render(scene, camera);
      }

      animate();
    </script>
  </body>
</html>
"""


class _ViewerHandler(BaseHTTPRequestHandler):
    ply_path = None
    title = ""

    def do_GET(self) -> None:
        self._handle_request(send_body=True)

    def do_HEAD(self) -> None:
        self._handle_request(send_body=False)

    def log_message(self, format, *args) -> None:
        return

    def _handle_request(self, send_body: bool) -> None:
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            content = (
                HTML_PAGE.replace("__TITLE_HTML__", html.escape(self.title))
                .replace("__TITLE_JS__", json.dumps(self.title))
                .encode("utf-8")
            )
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            if send_body:
                self.wfile.write(content)
            return

        if path == "/data.ply":
            size = self.ply_path.stat().st_size
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(size))
            self.end_headers()
            if send_body:
                with self.ply_path.open("rb") as handle:
                    while True:
                        chunk = handle.read(1024 * 1024)
                        if not chunk:
                            break
                        self.wfile.write(chunk)
            return

        self.send_error(404)


def _build_handler(ply_path: Path):
    class Handler(_ViewerHandler):
        pass

    Handler.ply_path = ply_path
    Handler.title = ply_path.name
    return Handler


def _print_ssh_hint(port: int) -> None:
    print("", flush=True)
    print("SSH tunnel from your local machine if needed:", flush=True)
    print(f"  ssh -L {port}:127.0.0.1:{port} <user>@<remote-host>", flush=True)
    print(f"  then open http://127.0.0.1:{port}/ locally", flush=True)


def serve_ply_viewer(ply_path: Path, port: int) -> int:
    ply_path = ply_path.expanduser().resolve()
    if not ply_path.is_file():
        raise SystemExit(f"PLY file not found: {ply_path}")

    handler = _build_handler(ply_path)
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    local_url = f"http://127.0.0.1:{port}/"

    print(f"Serving {ply_path}", flush=True)
    print(f"Open: {local_url}", flush=True)
    _print_ssh_hint(port)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()

    return 0

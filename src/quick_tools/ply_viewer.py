import html
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional, Tuple
from urllib.parse import urlparse

MAX_BROWSER_POINTS = 5_000_000
MAX_DIRECT_FILE_BYTES = 256 * 1024 * 1024

_PLY_SCALAR_SIZES = {
    b"char": 1,
    b"uchar": 1,
    b"int8": 1,
    b"uint8": 1,
    b"short": 2,
    b"ushort": 2,
    b"int16": 2,
    b"uint16": 2,
    b"int": 4,
    b"uint": 4,
    b"int32": 4,
    b"uint32": 4,
    b"float": 4,
    b"float32": 4,
    b"double": 8,
    b"float64": 8,
}


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

      .status {
        position: fixed;
        left: 12px;
        z-index: 10;
        padding: 10px 12px;
        border-radius: 8px;
        background: rgba(0, 0, 0, 0.68);
        font-size: 14px;
        line-height: 1.4;
        pointer-events: none;
      }

      #status-main {
        top: 12px;
      }

      #status-and {
        top: calc(50% + 12px);
        display: none;
      }

      #divider {
        position: fixed;
        left: 0;
        right: 0;
        top: 50%;
        height: 1px;
        z-index: 9;
        display: none;
        background: rgba(255, 255, 255, 0.48);
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
    <div id="status-main" class="status"></div>
    <div id="status-and" class="status"></div>
    <div id="divider"></div>
    <div id="app"></div>
    <script type="module">
      import * as THREE from "three";
      import { OrbitControls } from "three/addons/controls/OrbitControls.js";
      import { PLYLoader } from "three/addons/loaders/PLYLoader.js";

      const container = document.getElementById("app");
      const requestedPointSize = __POINT_SIZE_JS__;
      const viewSpecs = __VIEW_SPECS_JS__;
      const isSplit = viewSpecs.length > 1;
      const divider = document.getElementById("divider");
      divider.style.display = isSplit ? "block" : "none";

      const renderer = new THREE.WebGLRenderer({ antialias: true });
      renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
      renderer.setSize(window.innerWidth, window.innerHeight);
      renderer.outputColorSpace = THREE.SRGBColorSpace;
      container.appendChild(renderer.domElement);

      const camera = new THREE.PerspectiveCamera(
        55,
        window.innerWidth / Math.max(isSplit ? window.innerHeight / 2 : window.innerHeight, 1),
        0.01,
        1e6,
      );
      camera.up.set(0, 0, 1);
      camera.position.set(2, -2, 1.5);

      const controls = new OrbitControls(camera, renderer.domElement);
      controls.enableDamping = true;
      let userMovedCamera = false;
      controls.addEventListener("start", () => {
        userMovedCamera = true;
      });

      const loader = new PLYLoader();
      const views = viewSpecs.map((spec) => {
        const status = document.getElementById(spec.statusId);
        status.style.display = "block";
        status.textContent = isSplit
          ? `Loading ${spec.label}: ${spec.title}...`
          : `Loading ${spec.title}...`;

        const scene = new THREE.Scene();
        scene.background = new THREE.Color(0x050505);

        return {
          ...spec,
          scene,
          status,
          loaded: false,
          radius: 1,
        };
      });

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

      function setStatusLines(element, lines) {
        const nodes = [];
        lines.forEach((line, index) => {
          if (index) {
            nodes.push(document.createElement("br"));
          }
          nodes.push(document.createTextNode(line));
        });
        element.replaceChildren(...nodes);
      }

      function maybeFitCamera() {
        if (userMovedCamera || views.some((view) => !view.loaded)) {
          return;
        }

        const radius = Math.max(...views.map((view) => view.radius), 1);
        camera.near = Math.max(radius / 1000, 0.001);
        camera.far = radius * 20;
        camera.position.set(radius * 1.7, -radius * 1.7, radius * 1.1);
        camera.updateProjectionMatrix();
        controls.target.set(0, 0, 0);
        controls.update();
      }

      function loadView(view) {
        loader.load(
          view.path,
          (geometry) => {
            if (geometry.hasAttribute("normal")) {
              geometry.deleteAttribute("normal");
            }

            geometry.center();
            geometry.computeBoundingSphere();

            const radius = geometry.boundingSphere?.radius || 1;
            const material = new THREE.PointsMaterial({
              size: requestedPointSize ?? Math.max(radius / 400, 0.0025),
              sizeAttenuation: true,
              vertexColors: geometry.hasAttribute("color"),
            });

            const cloud = new THREE.Points(geometry, material);
            view.scene.add(cloud);
            view.loaded = true;
            view.radius = radius;

            const count = geometry.getAttribute("position").count.toLocaleString();
            const statusLines = isSplit
              ? [`${view.label}: ${view.title}`, `${count} points`]
              : [`${count} points`];
            if (view.downsampleMessage) {
              statusLines.push(view.downsampleMessage);
            }
            statusLines.push("Drag to orbit, scroll to zoom");
            setStatusLines(view.status, statusLines);
            maybeFitCamera();
          },
          (event) => {
            const loaded = formatBytes(event.loaded);
            const total = formatBytes(event.total);
            const prefix = isSplit ? `Loading ${view.label}: ${view.title}...` : `Loading ${view.title}...`;
            view.status.textContent = total ? `${prefix} ${loaded} / ${total}` : `${prefix} ${loaded}`;
          },
          (error) => {
            console.error(error);
            view.status.textContent = `Failed to load ${view.title}: ${error?.message || error}`;
          },
        );
      }

      views.forEach(loadView);

      window.addEventListener("resize", () => {
        renderer.setSize(window.innerWidth, window.innerHeight);
      });

      function getViewRect(index) {
        const width = window.innerWidth;
        const height = window.innerHeight;
        if (!isSplit) {
          return { x: 0, y: 0, width, height };
        }

        const bottomHeight = Math.floor(height / 2);
        if (index === 0) {
          return { x: 0, y: bottomHeight, width, height: height - bottomHeight };
        }
        return { x: 0, y: 0, width, height: bottomHeight };
      }

      function renderView(view, index) {
        const rect = getViewRect(index);
        camera.aspect = rect.width / Math.max(rect.height, 1);
        camera.updateProjectionMatrix();
        renderer.setViewport(rect.x, rect.y, rect.width, rect.height);
        renderer.setScissor(rect.x, rect.y, rect.width, rect.height);
        renderer.render(view.scene, camera);
      }

      function animate() {
        requestAnimationFrame(animate);
        controls.update();
        renderer.setScissorTest(isSplit);
        views.forEach(renderView);
      }

      animate();
    </script>
  </body>
</html>
"""


class _ViewerHandler(BaseHTTPRequestHandler):
    ply_path = None
    ply_bytes = None
    and_ply_path = None
    and_ply_bytes = None
    title = ""
    point_size = None
    view_specs = []

    def do_GET(self) -> None:
        self._handle_request(send_body=True)

    def do_HEAD(self) -> None:
        self._handle_request(send_body=False)

    def log_message(self, format, *args) -> None:
        return

    def _write_chunks(self, payload: bytes, chunk_size: int = 1024 * 1024) -> None:
        try:
            for start in range(0, len(payload), chunk_size):
                self.wfile.write(payload[start : start + chunk_size])
        except (BrokenPipeError, ConnectionResetError):
            return

    def _send_ply(self, ply_path: Path, ply_bytes: Optional[bytes], send_body: bool) -> None:
        if ply_bytes is not None:
            size = len(ply_bytes)
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(size))
            self.end_headers()
            if send_body:
                self._write_chunks(ply_bytes)
            return

        size = ply_path.stat().st_size
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(size))
        self.end_headers()
        if send_body:
            with ply_path.open("rb") as handle:
                try:
                    while True:
                        chunk = handle.read(1024 * 1024)
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    return

    def _handle_request(self, send_body: bool) -> None:
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            content = (
                HTML_PAGE.replace("__TITLE_HTML__", html.escape(self.title))
                .replace("__POINT_SIZE_JS__", "null" if self.point_size is None else repr(self.point_size))
                .replace("__VIEW_SPECS_JS__", json.dumps(self.view_specs))
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
            self._send_ply(self.ply_path, self.ply_bytes, send_body)
            return

        if path == "/and.ply" and self.and_ply_path is not None:
            self._send_ply(self.and_ply_path, self.and_ply_bytes, send_body)
            return

        self.send_error(404)


def _build_handler(
    ply_path: Path,
    ply_bytes=None,
    point_size=None,
    downsample_message=None,
    and_ply_path=None,
    and_ply_bytes=None,
    and_downsample_message=None,
):
    class Handler(_ViewerHandler):
        pass

    Handler.ply_path = ply_path
    Handler.ply_bytes = ply_bytes
    Handler.and_ply_path = and_ply_path
    Handler.and_ply_bytes = and_ply_bytes
    Handler.title = str(ply_path) if and_ply_path is None else f"{ply_path} + {and_ply_path}"
    Handler.point_size = point_size
    Handler.view_specs = [
        {
            "path": "/data.ply",
            "title": str(ply_path),
            "label": "Top",
            "statusId": "status-main",
            "downsampleMessage": downsample_message,
        }
    ]
    if and_ply_path is not None:
        Handler.view_specs.append(
            {
                "path": "/and.ply",
                "title": str(and_ply_path),
                "label": "Bottom",
                "statusId": "status-and",
                "downsampleMessage": and_downsample_message,
            }
        )
    return Handler


def _print_ssh_hint(port: int) -> None:
    print("", flush=True)
    print("SSH tunnel from your local machine if needed:", flush=True)
    print(f"  ssh -L {port}:127.0.0.1:{port} <user>@<remote-host>", flush=True)
    print(f"  then open http://127.0.0.1:{port}/ locally", flush=True)


def _read_ply_header(ply_path: Path):
    with ply_path.open("rb") as handle:
        first_line = handle.readline()
        if first_line.strip() != b"ply":
            raise RuntimeError(f"Unsupported PLY header in {ply_path}")

        format_name = None
        vertex_count = None
        vertex_stride = 0
        vertex_properties = []
        in_vertex_element = False

        while True:
            line = handle.readline()
            if not line:
                raise RuntimeError(f"Unexpected EOF while reading header from {ply_path}")

            stripped = line.strip()
            if stripped == b"end_header":
                return {
                    "format": format_name,
                    "vertex_count": vertex_count,
                    "vertex_stride": vertex_stride,
                    "vertex_properties": vertex_properties,
                    "data_offset": handle.tell(),
                }

            if not stripped:
                continue

            parts = stripped.split()
            keyword = parts[0]

            if keyword == b"format" and len(parts) >= 2:
                format_name = parts[1].decode("ascii")
                continue

            if keyword == b"element" and len(parts) >= 3:
                in_vertex_element = parts[1] == b"vertex"
                if in_vertex_element:
                    vertex_count = int(parts[2])
                continue

            if keyword == b"property" and in_vertex_element:
                if len(parts) < 3 or parts[1] == b"list":
                    raise RuntimeError(f"Unsupported vertex property layout in {ply_path}")
                property_type = parts[1]
                size = _PLY_SCALAR_SIZES.get(property_type)
                if size is None:
                    raise RuntimeError(f"Unsupported PLY property type {property_type!r} in {ply_path}")
                vertex_stride += size
                vertex_properties.append((property_type.decode("ascii"), parts[2].decode("ascii")))


def _build_sampled_ply_bytes(ply_path: Path) -> Optional[Tuple[bytes, int, int]]:
    file_size = ply_path.stat().st_size
    if file_size <= MAX_DIRECT_FILE_BYTES:
        return None

    header = _read_ply_header(ply_path)
    fmt = header["format"]
    vertex_count = header["vertex_count"]
    vertex_stride = header["vertex_stride"]
    data_offset = header["data_offset"]
    vertex_properties = header["vertex_properties"]

    if fmt not in {"binary_little_endian", "binary_big_endian"}:
        raise RuntimeError(
            f"{ply_path.name} is too large to load directly in a browser and unsupported for auto-downsampling"
        )
    if not vertex_count or not vertex_stride or not vertex_properties:
        raise RuntimeError(f"Could not determine vertex layout for {ply_path.name}")
    if vertex_count <= MAX_BROWSER_POINTS:
        return None

    step = (vertex_count + MAX_BROWSER_POINTS - 1) // MAX_BROWSER_POINTS
    sampled_count = (vertex_count + step - 1) // step

    header_lines = [
        b"ply\n",
        f"format {fmt} 1.0\n".encode("ascii"),
        f"element vertex {sampled_count}\n".encode("ascii"),
    ]
    header_lines.extend(
        f"property {property_type} {property_name}\n".encode("ascii")
        for property_type, property_name in vertex_properties
    )
    header_lines.append(b"end_header\n")

    sampled = bytearray(b"".join(header_lines))
    skip_bytes = (step - 1) * vertex_stride

    with ply_path.open("rb") as handle:
        handle.seek(data_offset)
        for _ in range(sampled_count):
            record = handle.read(vertex_stride)
            if len(record) != vertex_stride:
                break
            sampled.extend(record)
            if skip_bytes:
                handle.seek(skip_bytes, 1)

    print(
        f"Downsampling {ply_path.name} for browser viewing: "
        f"{vertex_count:,} -> {sampled_count:,} points",
        flush=True,
    )
    return bytes(sampled), vertex_count, sampled_count


def _prepare_browser_ply(ply_path: Path) -> Tuple[Optional[bytes], Optional[str]]:
    sampled = _build_sampled_ply_bytes(ply_path)
    if sampled is None:
        return None, None

    ply_bytes, original_count, sampled_count = sampled
    return ply_bytes, f"Downsampled: {original_count:,} -> {sampled_count:,} points"


def _show_ply_local(ply_path: Path, point_size: Optional[float]) -> int:
    try:
        import open3d as o3d
    except ImportError as exc:
        raise RuntimeError("`open3d` is not installed.") from exc

    geometry_type = o3d.io.read_file_geometry_type(str(ply_path))

    if geometry_type & o3d.io.CONTAINS_POINTS:
        geometry = o3d.io.read_point_cloud(str(ply_path))
    elif geometry_type & o3d.io.CONTAINS_TRIANGLES:
        geometry = o3d.io.read_triangle_mesh(str(ply_path))
    else:
        raise RuntimeError(f"Unsupported PLY geometry in {ply_path.name}")

    if geometry.is_empty():
        raise RuntimeError(f"Failed to load {ply_path.name}")

    vis = o3d.visualization.Visualizer()
    vis.create_window(window_name=ply_path.name)
    vis.add_geometry(geometry)
    if point_size is not None:
        vis.get_render_option().point_size = point_size
    vis.run()
    vis.destroy_window()
    return 0


def serve_ply_viewer(
    ply_path: Path,
    port: int,
    local: bool = False,
    point_size: Optional[float] = None,
    and_ply_path: Optional[Path] = None,
) -> int:
    ply_path = ply_path.expanduser().resolve()
    if not ply_path.is_file():
        raise SystemExit(f"PLY file not found: {ply_path}")
    if and_ply_path is not None:
        and_ply_path = and_ply_path.expanduser().resolve()
        if not and_ply_path.is_file():
            raise SystemExit(f"PLY file not found: {and_ply_path}")

    if local:
        if and_ply_path is not None:
            raise RuntimeError("--and is only supported in browser mode.")
        return _show_ply_local(ply_path, point_size)

    ply_bytes, downsample_message = _prepare_browser_ply(ply_path)
    and_ply_bytes = None
    and_downsample_message = None
    if and_ply_path is not None:
        and_ply_bytes, and_downsample_message = _prepare_browser_ply(and_ply_path)

    handler = _build_handler(
        ply_path,
        ply_bytes=ply_bytes,
        point_size=point_size,
        downsample_message=downsample_message,
        and_ply_path=and_ply_path,
        and_ply_bytes=and_ply_bytes,
        and_downsample_message=and_downsample_message,
    )
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    local_url = f"http://127.0.0.1:{port}/"

    print(f"Serving {ply_path}", flush=True)
    if and_ply_path is not None:
        print(f"Serving {and_ply_path}", flush=True)
    print(f"Open: {local_url}", flush=True)
    _print_ssh_hint(port)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()

    return 0

import html
import json
import tempfile
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse

MAX_BROWSER_POINTS = 5_000_000
MAX_DIRECT_FILE_BYTES = 256 * 1024 * 1024

_POSITION_TYPES = {"float", "float32", "double", "float64", "int", "int32"}
_COLOR_TYPES = {"uchar", "uint8"}
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


@dataclass
class _PlyProperty:
    property_type: str
    name: str
    offset: int = 0


@dataclass
class _PlyElement:
    name: str
    count: int
    properties: List[_PlyProperty]


@dataclass
class _ColorSet:
    label: str
    properties: Tuple[_PlyProperty, _PlyProperty, _PlyProperty]


@dataclass
class _PlyContract:
    fmt: str
    vertex_count: int
    vertex_properties: List[_PlyProperty]
    position_properties: Tuple[_PlyProperty, _PlyProperty, _PlyProperty]
    color_sets: List[_ColorSet]
    color_properties: Optional[Tuple[_PlyProperty, _PlyProperty, _PlyProperty]]
    vertex_stride: int
    data_offset: int


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

    def _send_ply(self, ply_bytes: bytes, send_body: bool) -> None:
        size = len(ply_bytes)
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(size))
        self.end_headers()
        if send_body:
            self._write_chunks(ply_bytes)

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
            self._send_ply(self.ply_bytes, send_body)
            return

        if path == "/and.ply" and self.and_ply_bytes is not None:
            self._send_ply(self.and_ply_bytes, send_body)
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


def _decode_header_value(value: bytes, ply_path: Path) -> str:
    try:
        return value.decode("ascii")
    except UnicodeDecodeError as exc:
        raise RuntimeError(f"PLY header must be ASCII: {ply_path}") from exc


def _prop_size(prop: _PlyProperty) -> int:
    return _PLY_SCALAR_SIZES[prop.property_type.encode("ascii")]


def _canonical_position_type(property_type: str) -> str:
    if property_type == "float32":
        return "float"
    if property_type == "float64":
        return "double"
    if property_type == "int32":
        return "int"
    return property_type


def _validate_color_set(color_set: _ColorSet, ply_path: Path) -> None:
    for prop in color_set.properties:
        if prop.property_type not in _COLOR_TYPES:
            raise RuntimeError(
                f"Color property {prop.name} must be uchar/uint8, got {prop.property_type}: {ply_path}"
            )


def _append_color_set(
    color_sets: List[_ColorSet],
    properties_by_name: Dict[str, _PlyProperty],
    names: Tuple[str, str, str],
    label: str,
    ply_path: Path,
) -> None:
    if not all(name in properties_by_name for name in names):
        return

    color_set = _ColorSet(label, tuple(properties_by_name[name] for name in names))
    _validate_color_set(color_set, ply_path)
    color_sets.append(color_set)


def _prefix_order(properties_by_name: Dict[str, _PlyProperty], suffixes: Tuple[str, str, str]) -> List[str]:
    prefixes = []
    seen = set()
    for name in properties_by_name:
        for suffix in suffixes:
            if name.endswith(suffix) and len(name) > len(suffix):
                prefix = name[: -len(suffix)]
                if prefix not in seen:
                    seen.add(prefix)
                    prefixes.append(prefix)
                break
    return prefixes


def _find_color_sets(properties_by_name: Dict[str, _PlyProperty], ply_path: Path) -> List[_ColorSet]:
    color_sets: List[_ColorSet] = []
    _append_color_set(color_sets, properties_by_name, ("r", "g", "b"), "r/g/b", ply_path)
    _append_color_set(color_sets, properties_by_name, ("red", "green", "blue"), "red/green/blue", ply_path)

    for prefix in _prefix_order(properties_by_name, ("_r", "_g", "_b")):
        names = (f"{prefix}_r", f"{prefix}_g", f"{prefix}_b")
        _append_color_set(color_sets, properties_by_name, names, "/".join(names), ply_path)

    for prefix in _prefix_order(properties_by_name, ("_red", "_green", "_blue")):
        names = (f"{prefix}_red", f"{prefix}_green", f"{prefix}_blue")
        _append_color_set(color_sets, properties_by_name, names, "/".join(names), ply_path)

    return color_sets


def _select_color_set(ply_path: Path, color_sets: List[_ColorSet]) -> Optional[_ColorSet]:
    if not color_sets:
        return None
    if len(color_sets) == 1:
        return color_sets[0]

    print(f"Multiple RGB color sets found in {ply_path}:", flush=True)
    for index, color_set in enumerate(color_sets, start=1):
        print(f"  {index}. {color_set.label}", flush=True)

    while True:
        try:
            choice = input(f"Select color set to use [1-{len(color_sets)}]: ").strip()
        except EOFError as exc:
            raise RuntimeError(f"Multiple RGB color sets found in {ply_path}; run interactively to choose one") from exc
        try:
            index = int(choice)
        except ValueError:
            print(f"Enter a number from 1 to {len(color_sets)}.", flush=True)
            continue
        if 1 <= index <= len(color_sets):
            color_set = color_sets[index - 1]
            print(f"Using RGB color set: {color_set.label}", flush=True)
            return color_set
        print(f"Enter a number from 1 to {len(color_sets)}.", flush=True)


def _read_ply_contract(ply_path: Path) -> _PlyContract:
    with ply_path.open("rb") as handle:
        first_line = handle.readline()
        if first_line.strip() != b"ply":
            raise RuntimeError(f"Expected PLY file to start with 'ply': {ply_path}")

        format_name = None
        elements = []
        current_element = None

        while True:
            line = handle.readline()
            if not line:
                raise RuntimeError(f"Unexpected EOF while reading header from {ply_path}")

            stripped = line.strip()
            if stripped == b"end_header":
                data_offset = handle.tell()
                break

            if not stripped:
                continue

            parts = stripped.split()
            keyword = parts[0]

            if keyword in {b"comment", b"obj_info"}:
                continue

            if keyword == b"format":
                if len(parts) < 3:
                    raise RuntimeError(f"Malformed PLY format line in {ply_path}")
                format_name = _decode_header_value(parts[1], ply_path)
                continue

            if keyword == b"element":
                if len(parts) < 3:
                    raise RuntimeError(f"Malformed PLY element line in {ply_path}")
                name = _decode_header_value(parts[1], ply_path)
                try:
                    count = int(parts[2])
                except ValueError as exc:
                    raise RuntimeError(f"Invalid element count for {name} in {ply_path}") from exc
                current_element = _PlyElement(name=name, count=count, properties=[])
                elements.append(current_element)
                continue

            if keyword == b"property":
                if current_element is None:
                    raise RuntimeError(f"PLY property appeared before any element in {ply_path}")
                if len(parts) < 3:
                    raise RuntimeError(f"Malformed PLY property line in {ply_path}")
                if parts[1] == b"list":
                    if len(parts) < 5:
                        raise RuntimeError(f"Malformed PLY list property line in {ply_path}")
                    current_element.properties.append(
                        _PlyProperty("list", _decode_header_value(parts[4], ply_path))
                    )
                else:
                    current_element.properties.append(
                        _PlyProperty(
                            _decode_header_value(parts[1], ply_path),
                            _decode_header_value(parts[2], ply_path),
                        )
                    )
                continue

            raise RuntimeError(f"Unsupported PLY header directive {keyword!r} in {ply_path}")

    if format_name not in {"ascii", "binary_little_endian", "binary_big_endian"}:
        raise RuntimeError(f"Unsupported PLY format {format_name!r} in {ply_path}")

    vertex_indices = [index for index, element in enumerate(elements) if element.name == "vertex"]
    if not vertex_indices:
        raise RuntimeError(f"Missing required element: vertex in {ply_path}")
    if len(vertex_indices) > 1:
        raise RuntimeError(f"PLY must contain exactly one vertex element: {ply_path}")
    if vertex_indices[0] != 0:
        raise RuntimeError(f"Vertex element must be first so other elements can be ignored: {ply_path}")

    vertex_element = elements[vertex_indices[0]]
    if vertex_element.count <= 0:
        raise RuntimeError(f"Vertex count must be greater than zero in {ply_path}")

    vertex_stride = 0
    properties_by_name: Dict[str, _PlyProperty] = {}
    for prop in vertex_element.properties:
        if prop.property_type == "list":
            raise RuntimeError(f"Vertex property {prop.name} must be scalar, not list: {ply_path}")
        if prop.name in properties_by_name:
            raise RuntimeError(f"Duplicate vertex property {prop.name}: {ply_path}")
        if prop.property_type.encode("ascii") not in _PLY_SCALAR_SIZES:
            raise RuntimeError(f"Unsupported vertex property type {prop.property_type!r}: {ply_path}")
        prop.offset = vertex_stride
        vertex_stride += _prop_size(prop)
        properties_by_name[prop.name] = prop

    missing_positions = [name for name in ("x", "y", "z") if name not in properties_by_name]
    if missing_positions:
        raise RuntimeError(f"Missing required vertex property/properties {', '.join(missing_positions)}: {ply_path}")

    position_properties = tuple(properties_by_name[name] for name in ("x", "y", "z"))
    for prop in position_properties:
        if prop.property_type not in _POSITION_TYPES:
            raise RuntimeError(
                f"Position property {prop.name} must be float/double/int, got {prop.property_type}: {ply_path}"
            )

    color_sets = _find_color_sets(properties_by_name, ply_path)
    color_properties = None

    return _PlyContract(
        fmt=format_name,
        vertex_count=vertex_element.count,
        vertex_properties=vertex_element.properties,
        position_properties=position_properties,
        color_sets=color_sets,
        color_properties=color_properties,
        vertex_stride=vertex_stride,
        data_offset=data_offset,
    )


def _sample_step(ply_path: Path, vertex_count: int) -> int:
    if ply_path.stat().st_size <= MAX_DIRECT_FILE_BYTES or vertex_count <= MAX_BROWSER_POINTS:
        return 1
    return (vertex_count + MAX_BROWSER_POINTS - 1) // MAX_BROWSER_POINTS


def _sampled_count(vertex_count: int, step: int) -> int:
    return (vertex_count + step - 1) // step


def _build_normalized_header(contract: _PlyContract, vertex_count: int) -> bytes:
    header_lines = [
        b"ply\n",
        f"format {contract.fmt} 1.0\n".encode("ascii"),
        f"element vertex {vertex_count}\n".encode("ascii"),
    ]
    for prop in contract.position_properties:
        header_lines.append(f"property {_canonical_position_type(prop.property_type)} {prop.name}\n".encode("ascii"))
    if contract.color_properties is not None:
        header_lines.extend([b"property uchar red\n", b"property uchar green\n", b"property uchar blue\n"])
    header_lines.append(b"end_header\n")
    return b"".join(header_lines)


def _iter_ascii_tokens(handle):
    pending = b""
    while True:
        chunk = handle.read(1024 * 1024)
        if not chunk:
            break
        data = pending + chunk
        parts = data.split()
        if data[-1:].isspace():
            pending = b""
        elif parts:
            pending = parts.pop()
        else:
            pending = data
        for part in parts:
            yield part
    if pending:
        yield pending


def _validate_ascii_value(token: bytes, prop: _PlyProperty, ply_path: Path) -> None:
    try:
        if prop.property_type in {"int", "int32"}:
            int(token)
        elif prop.property_type in _POSITION_TYPES:
            float(token)
        elif prop.property_type in _COLOR_TYPES:
            value = int(token)
            if value < 0 or value > 255:
                raise ValueError
    except ValueError as exc:
        raise RuntimeError(f"Invalid value for vertex property {prop.name}: {token!r} in {ply_path}") from exc


def _normalize_ascii_ply(ply_path: Path, contract: _PlyContract, step: int, count: int) -> bytes:
    output = bytearray(_build_normalized_header(contract, count))
    property_indices = {prop.name: index for index, prop in enumerate(contract.vertex_properties)}
    selected_properties = list(contract.position_properties)
    if contract.color_properties is not None:
        selected_properties.extend(contract.color_properties)
    selected_indices = [property_indices[prop.name] for prop in selected_properties]

    with ply_path.open("rb") as handle:
        handle.seek(contract.data_offset)
        tokens = _iter_ascii_tokens(handle)
        for vertex_index in range(contract.vertex_count):
            values = []
            for _ in contract.vertex_properties:
                try:
                    values.append(next(tokens))
                except StopIteration as exc:
                    raise RuntimeError(f"Unexpected EOF while reading vertex data from {ply_path}") from exc
            row = [values[index] for index in selected_indices]
            for token, prop in zip(row, selected_properties):
                _validate_ascii_value(token, prop, ply_path)
            if vertex_index % step:
                continue
            output.extend(b" ".join(row))
            output.extend(b"\n")

    return bytes(output)


def _normalize_binary_ply(ply_path: Path, contract: _PlyContract, step: int, count: int) -> bytes:
    output = bytearray(_build_normalized_header(contract, count))
    selected_properties = list(contract.position_properties)
    if contract.color_properties is not None:
        selected_properties.extend(contract.color_properties)

    skip_bytes = (step - 1) * contract.vertex_stride

    with ply_path.open("rb") as handle:
        handle.seek(contract.data_offset)
        for _ in range(count):
            record = handle.read(contract.vertex_stride)
            if len(record) != contract.vertex_stride:
                raise RuntimeError(f"Unexpected EOF while reading vertex data from {ply_path}")
            for prop in selected_properties:
                output.extend(record[prop.offset : prop.offset + _prop_size(prop)])
            if skip_bytes:
                handle.seek(skip_bytes, 1)

    return bytes(output)


def _prepare_ply(ply_path: Path) -> Tuple[bytes, Optional[str]]:
    contract = _read_ply_contract(ply_path)
    color_set = _select_color_set(ply_path, contract.color_sets)
    contract.color_properties = None if color_set is None else color_set.properties
    step = _sample_step(ply_path, contract.vertex_count)
    count = _sampled_count(contract.vertex_count, step)
    if contract.fmt == "ascii":
        ply_bytes = _normalize_ascii_ply(ply_path, contract, step, count)
    else:
        ply_bytes = _normalize_binary_ply(ply_path, contract, step, count)

    if step == 1:
        return ply_bytes, None

    print(
        f"Downsampling {ply_path.name} for browser viewing: "
        f"{contract.vertex_count:,} -> {count:,} points",
        flush=True,
    )
    return ply_bytes, f"Downsampled: {contract.vertex_count:,} -> {count:,} points"


def _show_ply_local(ply_path: Path, ply_bytes: bytes, point_size: Optional[float]) -> int:
    try:
        import open3d as o3d
    except ImportError as exc:
        raise RuntimeError("`open3d` is not installed.") from exc

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".ply", delete=False) as tmp:
            tmp.write(ply_bytes)
            tmp_path = Path(tmp.name)
        geometry = o3d.io.read_point_cloud(str(tmp_path))
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)

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
    if local and and_ply_path is not None:
        raise RuntimeError("--and is only supported in browser mode.")

    ply_bytes, downsample_message = _prepare_ply(ply_path)

    if local:
        return _show_ply_local(ply_path, ply_bytes, point_size)

    and_ply_bytes = None
    and_downsample_message = None
    if and_ply_path is not None:
        and_ply_bytes, and_downsample_message = _prepare_ply(and_ply_path)

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

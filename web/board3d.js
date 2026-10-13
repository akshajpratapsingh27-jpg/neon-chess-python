const THREE_URL = 'https://cdn.jsdelivr.net/npm/three@0.180.0/build/three.module.js';
const CONTROLS_URL = 'https://cdn.jsdelivr.net/npm/three@0.180.0/examples/jsm/controls/OrbitControls.js';
const THREE = await import(THREE_URL);
const { OrbitControls } = await import(CONTROLS_URL);

const COLORS = {
  light: 0x1c3b51,
  dark: 0x0b1725,
  edge: 0x0b101b,
  cyan: 0x5ce7ff,
  amber: 0xffca75,
  check: 0xff718b,
  whitePiece: 0xeaf6ff,
  blackPiece: 0x1b2f49
};

export async function createBoard3D(canvas, callbacks = {}) {
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;

  const scene = new THREE.Scene();
  scene.fog = new THREE.Fog(0x070a12, 13, 28);
  const camera = new THREE.PerspectiveCamera(40, 1, 0.1, 100);
  const defaultCamera = new THREE.Vector3(8.7, 10.5, 10.5);
  camera.position.copy(defaultCamera);
  const controls = new OrbitControls(camera, canvas);
  controls.enableDamping = true;
  controls.enablePan = false;
  controls.minDistance = 9;
  controls.maxDistance = 24;
  controls.minPolarAngle = 0.12;
  controls.maxPolarAngle = Math.PI / 2 - 0.08;
  controls.target.set(0, 0, 0);

  scene.add(new THREE.HemisphereLight(0x9ddfff, 0x080b13, 2.5));
  const keyLight = new THREE.DirectionalLight(0xffffff, 3.5);
  keyLight.position.set(-4, 10, 5);
  keyLight.castShadow = true;
  keyLight.shadow.mapSize.set(1024, 1024);
  scene.add(keyLight);
  const cyanLight = new THREE.PointLight(COLORS.cyan, 12, 12, 2);
  cyanLight.position.set(-4, 3, -4);
  scene.add(cyanLight);
  const violetLight = new THREE.PointLight(0x775cff, 10, 10, 2);
  violetLight.position.set(5, 2, 4);
  scene.add(violetLight);

  const boardGroup = new THREE.Group();
  const pieceLayer = new THREE.Group();
  const markerLayer = new THREE.Group();
  boardGroup.add(pieceLayer, markerLayer);
  scene.add(boardGroup);

  const geometryCache = new Map();
  const materialCache = new Map();
  const squareMaterials = [];

  const baseGeometry = new THREE.BoxGeometry(8.65, 0.42, 8.65);
  const baseMaterial = new THREE.MeshStandardMaterial({ color: COLORS.edge, metalness: 0.45, roughness: 0.4 });
  const base = new THREE.Mesh(baseGeometry, baseMaterial);
  base.position.y = -0.26;
  base.receiveShadow = true;
  boardGroup.add(base);

  const squareMeshes = [];
  for (let rank = 0; rank < 8; rank += 1) {
    for (let file = 0; file < 8; file += 1) {
      const material = new THREE.MeshStandardMaterial({
        color: (file + rank) % 2 ? COLORS.light : COLORS.dark,
        metalness: 0.1,
        roughness: 0.62
      });
      squareMaterials.push(material);
      const square = new THREE.Mesh(cachedGeometry(`square-${file}-${rank}`, () => new THREE.BoxGeometry(1, 0.16, 1)), material);
      square.position.set(file - 3.5, 0, 3.5 - rank);
      square.userData.square = rank * 8 + file;
      square.receiveShadow = true;
      squareMeshes.push(square);
      boardGroup.add(square);
    }
  }

  const markerGeometry = new THREE.CylinderGeometry(0.23, 0.23, 0.055, 24);
  const markerMaterials = new Map();
  let disposed = false;
  let animationFrame = 0;

  const resize = () => {
    const rect = canvas.getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    renderer.setSize(rect.width, rect.height, false);
    camera.aspect = rect.width / rect.height;
    // Give narrow canvases more vertical FOV so the complete board remains visible.
    camera.fov = Math.max(40, Math.min(54, 40 / Math.max(camera.aspect, 0.6)));
    camera.updateProjectionMatrix();
  };
  const observer = typeof ResizeObserver === 'function' ? new ResizeObserver(resize) : null;
  if (observer) observer.observe(canvas);
  else window.addEventListener('resize', resize);

  const animate = () => {
    if (disposed) return;
    controls.update();
    renderer.render(scene, camera);
    animationFrame = requestAnimationFrame(animate);
  };
  animate();

  const raycaster = new THREE.Raycaster();
  const pointer = new THREE.Vector2();
  let pointerDown = null;

  function pointerPosition(event) {
    const rect = canvas.getBoundingClientRect();
    pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
    pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
    raycaster.setFromCamera(pointer, camera);
  }

  function objectSquare(object) {
    let current = object;
    while (current) {
      if (current.userData.square !== undefined) return current.userData.square;
      current = current.parent;
    }
    return null;
  }

  function pickSquare(event, objects) {
    pointerPosition(event);
    const hits = raycaster.intersectObjects(objects, true);
    for (const hit of hits) {
      const square = objectSquare(hit.object);
      if (square !== null) return square;
    }
    return null;
  }

  canvas.addEventListener('pointerdown', (event) => {
    if (event.button !== 0) return;
    pointerPosition(event);
    const pieceHits = raycaster.intersectObjects(pieceLayer.children, true);
    const source = pieceHits.map((hit) => objectSquare(hit.object)).find((value) => value !== null);
    const canDrag = source !== undefined && source !== null && callbacks.canDrag?.(source) !== false;
    pointerDown = { x: event.clientX, y: event.clientY, source: canDrag ? source : null, moved: false };
    if (canDrag) {
      controls.enabled = false;
      canvas.style.cursor = 'grabbing';
      canvas.setPointerCapture?.(event.pointerId);
      event.preventDefault();
    }
  });

  canvas.addEventListener('pointermove', (event) => {
    if (!pointerDown) return;
    pointerDown.moved = pointerDown.moved || Math.hypot(event.clientX - pointerDown.x, event.clientY - pointerDown.y) > 6;
  });

  canvas.addEventListener('pointerup', (event) => {
    if (!pointerDown) return;
    const active = pointerDown;
    pointerDown = null;
    controls.enabled = true;
    canvas.style.cursor = '';
    canvas.releasePointerCapture?.(event.pointerId);
    const objects = [...squareMeshes, ...pieceLayer.children, ...markerLayer.children];
    const target = pickSquare(event, objects);
    if (active.source !== null) {
      if (active.moved && target !== null) callbacks.onDrag?.(active.source, target);
      else if (!active.moved) callbacks.onSquare?.(active.source);
      return;
    }
    if (!active.moved && target !== null) callbacks.onSquare?.(target);
  });

  canvas.addEventListener('pointercancel', (event) => {
    pointerDown = null;
    controls.enabled = true;
    canvas.style.cursor = '';
    canvas.releasePointerCapture?.(event.pointerId);
  });

  const controller = {
    sync(snapshot) {
      boardGroup.rotation.y = snapshot.flipped ? Math.PI : 0;
      clearLayer(pieceLayer);
      clearLayer(markerLayer);
      const lastFrom = snapshot.lastMove ? snapshot.lastMove.slice(0, 2) : '';
      const lastTo = snapshot.lastMove ? snapshot.lastMove.slice(2, 4) : '';
      snapshot.board.forEach((piece, index) => {
        if (!piece) return;
        const mesh = createPiece(piece);
        mesh.position.copy(squarePosition(index));
        mesh.position.y = 0.12;
        mesh.userData.square = index;
        mesh.traverse((child) => { child.userData.square = index; });
        if (squareName(index) === lastFrom || squareName(index) === lastTo) mesh.scale.multiplyScalar(1.04);
        pieceLayer.add(mesh);
      });
      if (snapshot.selected !== null) {
        addMarker(snapshot.selected, COLORS.cyan, 0.17);
        snapshot.legalMoves
          .filter((move) => move.slice(0, 2) === squareName(snapshot.selected))
          .forEach((move) => addMarker(squareIndex(move.slice(2, 4)), snapshot.board[squareIndex(move.slice(2, 4))] ? COLORS.amber : COLORS.cyan, 0.14));
      }
      if (snapshot.inCheck) {
        const king = snapshot.board.findIndex((piece) => piece === (snapshot.turn === 'white' ? 'K' : 'k'));
        if (king >= 0) addMarker(king, COLORS.check, 0.205);
      }
      resize();
    },
    setCamera(mode) {
      if (mode === 1) camera.position.set(0, 16.5, 0.01);
      else if (mode === 2) camera.position.set(8.9, 8.0, 9.2);
      else camera.position.copy(defaultCamera);
      controls.update();
      resize();
    },
    resize,
    dispose() {
      disposed = true;
      cancelAnimationFrame(animationFrame);
      if (observer) observer.disconnect();
      else window.removeEventListener('resize', resize);
      controls.dispose();
      geometryCache.forEach((geometry) => geometry.dispose());
      materialCache.forEach((material) => material.dispose());
      squareMaterials.forEach((material) => material.dispose());
      markerMaterials.forEach((material) => material.dispose());
      baseGeometry.dispose();
      baseMaterial.dispose();
      markerGeometry.dispose();
      renderer.dispose();
    }
  };

  resize();
  return controller;

  function cachedGeometry(key, factory) {
    if (!geometryCache.has(key)) geometryCache.set(key, factory());
    return geometryCache.get(key);
  }

  function clearLayer(layer) {
    while (layer.children.length) layer.remove(layer.children[layer.children.length - 1]);
  }

  function squarePosition(index) {
    return new THREE.Vector3(index % 8 - 3.5, 0, 3.5 - Math.floor(index / 8));
  }

  function squareIndex(name) {
    return 'abcdefgh'.indexOf(name[0]) + 8 * (Number(name[1]) - 1);
  }

  function squareName(index) {
    return 'abcdefgh'[index % 8] + (Math.floor(index / 8) + 1);
  }

  function pieceMaterial(piece) {
    const key = piece === piece.toUpperCase() ? 'white' : 'black';
    if (!materialCache.has(key)) {
      materialCache.set(key, new THREE.MeshStandardMaterial({
        color: key === 'white' ? COLORS.whitePiece : COLORS.blackPiece,
        metalness: key === 'white' ? 0.25 : 0.6,
        roughness: key === 'white' ? 0.28 : 0.35,
        emissive: key === 'white' ? 0x18334a : 0x050d1a,
        emissiveIntensity: 0.5
      }));
    }
    return materialCache.get(key);
  }

  function addPart(group, key, factory, y, material, transform = {}) {
    const value = new THREE.Mesh(cachedGeometry(key, factory), material);
    value.position.y = y;
    if (transform.x) value.position.x = transform.x;
    if (transform.z) value.position.z = transform.z;
    if (transform.rotationZ) value.rotation.z = transform.rotationZ;
    group.add(value);
    return value;
  }

  function createPiece(piece) {
    const kind = piece.toLowerCase();
    const pieceMaterialValue = pieceMaterial(piece);
    const group = new THREE.Group();
    addPart(group, 'piece-base', () => new THREE.CylinderGeometry(0.31, 0.4, 0.16, 24), 0.1, pieceMaterialValue);
    if (kind === 'p') {
      addPart(group, 'pawn-body', () => new THREE.CylinderGeometry(0.2, 0.27, 0.42, 20), 0.36, pieceMaterialValue);
      addPart(group, 'pawn-head', () => new THREE.SphereGeometry(0.2, 20, 12), 0.68, pieceMaterialValue);
    } else if (kind === 'n') {
      addPart(group, 'knight-body', () => new THREE.CylinderGeometry(0.21, 0.29, 0.45, 20), 0.38, pieceMaterialValue);
      addPart(group, 'knight-head', () => new THREE.ConeGeometry(0.3, 0.62, 5), 0.78, pieceMaterialValue, { rotationZ: -0.2, z: -0.02 });
    } else if (kind === 'b') {
      addPart(group, 'bishop-body', () => new THREE.ConeGeometry(0.29, 0.7, 20), 0.48, pieceMaterialValue);
      addPart(group, 'bishop-head', () => new THREE.SphereGeometry(0.18, 18, 10), 0.92, pieceMaterialValue);
      addPart(group, 'bishop-collar', () => new THREE.TorusGeometry(0.2, 0.045, 8, 20), 0.72, pieceMaterialValue);
    } else if (kind === 'r') {
      addPart(group, 'rook-body', () => new THREE.CylinderGeometry(0.27, 0.31, 0.68, 12), 0.48, pieceMaterialValue);
      addPart(group, 'rook-top', () => new THREE.CylinderGeometry(0.34, 0.34, 0.16, 8), 0.88, pieceMaterialValue);
    } else if (kind === 'q') {
      addPart(group, 'queen-body', () => new THREE.ConeGeometry(0.3, 0.74, 16), 0.48, pieceMaterialValue);
      addPart(group, 'queen-collar', () => new THREE.TorusGeometry(0.2, 0.055, 8, 20), 0.86, pieceMaterialValue);
      addPart(group, 'queen-crown', () => new THREE.SphereGeometry(0.12, 16, 10), 1.05, pieceMaterialValue);
    } else {
      addPart(group, 'king-body', () => new THREE.CylinderGeometry(0.27, 0.34, 0.72, 20), 0.5, pieceMaterialValue);
      addPart(group, 'king-cross-horizontal', () => new THREE.BoxGeometry(0.52, 0.13, 0.13), 0.93, pieceMaterialValue);
      addPart(group, 'king-cross-vertical', () => new THREE.BoxGeometry(0.13, 0.13, 0.52), 0.93, pieceMaterialValue);
    }
    group.scale.setScalar(0.82);
    group.traverse((child) => { child.castShadow = true; });
    return group;
  }

  function addMarker(index, color, y) {
    if (!markerMaterials.has(color)) markerMaterials.set(color, new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.88 }));
    const marker = new THREE.Mesh(markerGeometry, markerMaterials.get(color));
    marker.position.copy(squarePosition(index));
    marker.position.y = y;
    marker.userData.square = index;
    marker.renderOrder = 3;
    markerLayer.add(marker);
  }
}

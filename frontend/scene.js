import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

const stage = document.getElementById('scene-stage');
const canvas = document.getElementById('hero-canvas');
const resetButton = document.getElementById('reset-view');

if (stage && canvas) {
  try {
    const renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true, powerPreference: 'high-performance' });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5));
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.55;
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;

    const scene = new THREE.Scene();
    scene.fog = new THREE.Fog(0x0b0d0c, 16, 30);

    const camera = new THREE.PerspectiveCamera(32, 1, 0.1, 50);
    const homePosition = new THREE.Vector3(11.8, 9.4, 12.9);
    camera.position.copy(homePosition);

    const controls = new OrbitControls(camera, canvas);
    controls.target.set(0, 1.1, 0);
    controls.enableDamping = true;
    controls.dampingFactor = 0.07;
    controls.enablePan = false;
    controls.enableZoom = false;
    controls.minPolarAngle = 0.55;
    controls.maxPolarAngle = 1.38;
    controls.update();

    const material = (color, roughness = 0.8, metalness = 0) =>
      new THREE.MeshStandardMaterial({ color, roughness, metalness });
    const stone = material(0x303431, 0.96);
    const floorTop = material(0x454a46, 0.96);
    const wall = material(0x242824, 0.88);
    const wallCap = material(0x777c77, 0.74);
    const furniture = material(0x171b18, 0.92);
    const furnitureTop = material(0x424742, 0.85);
    const upholstery = material(0x323732, 0.96);
    const cushion = material(0x777d77, 0.96);
    const screen = new THREE.MeshBasicMaterial({ color: 0x1b1f1d, toneMapped: false });
    const glass = new THREE.MeshStandardMaterial({ color: 0xffffff, roughness: 0.24, transparent: true, opacity: 0.4 });
    const lime = new THREE.Color(0xb8f46b);

    function box(width, height, depth, x, y, z, surface, shadow = true) {
      const mesh = new THREE.Mesh(new THREE.BoxGeometry(width, height, depth), surface);
      mesh.position.set(x, y, z);
      mesh.castShadow = shadow;
      mesh.receiveShadow = true;
      scene.add(mesh);
      return mesh;
    }

    function groupSince(start) {
      const group = new THREE.Group();
      scene.children.slice(start).forEach((object) => group.add(object));
      scene.add(group);
      return group;
    }

    // A cutaway architectural model: the two open sides keep the interior visible.
    let groupStart = scene.children.length;
    box(11.6, 0.24, 8.8, 0, -0.18, 0, stone, false);
    box(11.3, 0.035, 8.5, 0, -0.035, 0, floorTop, false);
    const floorGroup = groupSince(groupStart);
    groupStart = scene.children.length;
    box(11.6, 2.2, 0.18, 0, 1.1, -4.35, wall);
    box(0.18, 2.2, 8.8, -5.75, 1.1, 0, wall);
    box(3.85, 1.65, 0.13, -3.84, 0.825, 0.18, wall);
    box(0.13, 1.4, 2.8, 1.85, 0.7, -2.95, wall);
    box(2.5, 1.2, 0.13, 4.48, 0.6, 1.5, wall);

    // Pale wall caps and a doorway suggest a real interior without closing the model.
    box(11.6, 0.06, 0.22, 0, 2.23, -4.35, wallCap, false);
    box(0.22, 0.06, 8.8, -5.75, 2.23, 0, wallCap, false);
    box(3.85, 0.05, 0.16, -3.84, 1.67, 0.18, wallCap, false);
    box(0.16, 0.05, 2.8, 1.85, 1.42, -2.95, wallCap, false);
    const wallGroup = groupSince(groupStart);

    // Furniture stays around the edges, leaving the central sensing area open.
    groupStart = scene.children.length;
    box(1.55, 0.12, 0.88, -3.2, 0.65, -2.35, furnitureTop);
    for (const x of [-3.8, -2.6]) for (const z of [-2.66, -2.04]) {
      box(0.09, 0.62, 0.09, x, 0.31, z, furniture);
    }
    function chair(z, backDirection) {
      box(0.49, 0.09, 0.47, -3.2, 0.4, z, furnitureTop);
      box(0.49, 0.54, 0.08, -3.2, 0.69, z + backDirection * 0.21, upholstery);
      for (const dx of [-0.18, 0.18]) for (const dz of [-0.17, 0.17]) {
        box(0.055, 0.37, 0.055, -3.2 + dx, 0.19, z + dz, furniture);
      }
    }
    chair(-1.3, 1);
    chair(-3.35, -1);

    box(1.48, 0.72, 0.62, 3.5, 0.36, -3.1, furniture);
    box(1.5, 0.06, 0.66, 3.5, 0.75, -3.1, furnitureTop);
    for (const x of [3.16, 3.84]) {
      box(0.63, 0.55, 0.025, x, 0.38, -2.78, upholstery);
      box(0.035, 0.13, 0.035, x + (x < 3.5 ? 0.19 : -0.19), 0.38, -2.75, wallCap);
    }

    // Sofa and side table occupy the front-left corner, clear of its sensor node.
    box(1.86, 0.28, 0.76, -3.15, 0.29, 2.73, upholstery);
    box(1.86, 0.64, 0.17, -3.15, 0.59, 3.09, upholstery);
    box(0.17, 0.48, 0.77, -4.0, 0.42, 2.73, upholstery);
    box(0.17, 0.48, 0.77, -2.3, 0.42, 2.73, upholstery);
    for (const x of [-3.7, -3.15, -2.6]) box(0.49, 0.1, 0.6, x, 0.48, 2.68, cushion);
    box(0.45, 0.38, 0.45, -1.9, 0.19, 2.9, furniture);
    box(0.5, 0.05, 0.5, -1.9, 0.4, 2.9, furnitureTop);

    // A quiet wall-mounted TV faces the sofa; windows break up the back wall.
    box(1.68, 0.95, 0.09, -3.75, 1.08, 0.28, furniture);
    box(1.5, 0.77, 0.02, -3.75, 1.08, 0.34, screen, false);
    for (const x of [-3.45, 0.15]) {
      box(1.2, 0.78, 0.025, x, 1.46, -4.23, glass, false);
      box(1.3, 0.05, 0.06, x, 1.88, -4.2, wallCap, false);
      box(1.3, 0.05, 0.06, x, 1.04, -4.2, wallCap, false);
      box(0.05, 0.84, 0.06, x - 0.63, 1.46, -4.2, wallCap, false);
      box(0.05, 0.84, 0.06, x + 0.63, 1.46, -4.2, wallCap, false);
    }
    const furnitureGroup = groupSince(groupStart);
    const furniturePieces = furnitureGroup.children.map((mesh) => ({ mesh, y: mesh.position.y }));

    const hemi = new THREE.HemisphereLight(0xffffff, 0x1b1f1d, 2.25);
    scene.add(hemi);
    const sun = new THREE.DirectionalLight(0xffffff, 3.15);
    sun.position.set(5, 9, 6);
    sun.castShadow = true;
    sun.shadow.mapSize.set(1024, 1024);
    sun.shadow.camera.left = -11;
    sun.shadow.camera.right = 11;
    sun.shadow.camera.top = 11;
    sun.shadow.camera.bottom = -11;
    sun.shadow.normalBias = 0.025;
    scene.add(sun);
    const fill = new THREE.PointLight(0xb8f46b, 15, 11, 2);
    fill.position.set(-3, 4, -1);
    scene.add(fill);

    // One sender broadcasts to three receivers. Each receiver reports to the gateway.
    const senderPosition = new THREE.Vector3(0, 2.15, -3.95);
    const nodePositions = [
      new THREE.Vector3(-4.55, 0.55, 1.0),
      new THREE.Vector3(0, 0.55, -1.65),
      new THREE.Vector3(4.45, 0.55, 1.0)
    ];
    const gatewayPosition = new THREE.Vector3(0, 0.7, 3.35);
    const displayPosition = new THREE.Vector3(3.75, 0.57, 3.5);
    const nodeBody = material(0x1b1f1d, 0.43, 0.34);
    const nodeMetal = material(0x8d938d, 0.32, 0.46);
    const beacon = new THREE.MeshBasicMaterial({ color: lime, toneMapped: false });

    function horizontalRing(radius, x, y, z, opacity, color = 0xb8f46b) {
      const ring = new THREE.Mesh(
        new THREE.TorusGeometry(radius, 0.012, 6, 72),
        new THREE.MeshBasicMaterial({ color, transparent: true, opacity, depthWrite: false })
      );
      ring.rotation.x = Math.PI / 2;
      ring.position.set(x, y, z);
      scene.add(ring);
      return ring;
    }

    function deviceLabel(label, color, x, y, z) {
      const labelCanvas = document.createElement('canvas');
      labelCanvas.width = 256;
      labelCanvas.height = 64;
      const context = labelCanvas.getContext('2d');
      context.fillStyle = 'rgba(11, 13, 12, 0.88)';
      context.fillRect(0, 0, 256, 64);
      context.strokeStyle = color;
      context.lineWidth = 3;
      context.strokeRect(2, 2, 252, 60);
      context.fillStyle = color;
      context.font = 'bold 27px Arial';
      context.textAlign = 'center';
      context.textBaseline = 'middle';
      context.fillText(label, 128, 33);
      const texture = new THREE.CanvasTexture(labelCanvas);
      texture.colorSpace = THREE.SRGBColorSpace;
      const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: texture, transparent: true, depthTest: false }));
      sprite.position.set(x, y, z);
      sprite.scale.set(1.55, 0.39, 1);
      scene.add(sprite);
    }

    groupStart = scene.children.length;
    box(0.82, 0.28, 0.28, senderPosition.x, senderPosition.y, senderPosition.z, nodeBody);
    box(0.5, 0.08, 0.3, senderPosition.x, senderPosition.y + 0.19, senderPosition.z, nodeMetal);
    const senderBeacon = new THREE.Mesh(new THREE.SphereGeometry(0.075, 16, 12), new THREE.MeshBasicMaterial({ color: 0xffffff, toneMapped: false }));
    senderBeacon.position.copy(senderPosition).add(new THREE.Vector3(0, 0.25, 0));
    scene.add(senderBeacon);
    deviceLabel('SENDER', '#ffffff', senderPosition.x, senderPosition.y + 0.7, senderPosition.z);
    nodePositions.forEach((position, index) => {
      const base = new THREE.Mesh(new THREE.CylinderGeometry(0.09, 0.12, 0.5, 12), nodeMetal);
      base.position.set(position.x, 0.25, position.z);
      base.castShadow = true;
      scene.add(base);
      box(0.42, 0.09, 0.32, position.x, 0.53, position.z, nodeBody);
      const antenna = new THREE.Mesh(new THREE.CylinderGeometry(0.012, 0.012, 0.33, 8), nodeMetal);
      antenna.position.set(position.x - 0.13, 0.74, position.z);
      scene.add(antenna);
      const light = new THREE.Mesh(new THREE.SphereGeometry(0.067, 16, 12), beacon);
      light.position.set(position.x, 0.64, position.z);
      scene.add(light);
      horizontalRing(0.32, position.x, 0.035, position.z, 0.56);
      deviceLabel(`NODE ${index + 1}`, '#b8f46b', position.x, 1.35, position.z);
    });
    box(0.46, 0.55, 0.4, gatewayPosition.x, 0.28, gatewayPosition.z, nodeBody);
    box(0.29, 0.32, 0.025, gatewayPosition.x, 0.36, gatewayPosition.z + 0.215, screen, false);
    const gatewayAntenna = new THREE.Mesh(new THREE.CylinderGeometry(0.014, 0.014, 0.4, 8), nodeMetal);
    gatewayAntenna.position.set(gatewayPosition.x, 0.76, gatewayPosition.z);
    scene.add(gatewayAntenna);
    const gatewayBeacon = new THREE.Mesh(new THREE.SphereGeometry(0.065, 16, 12), beacon);
    gatewayBeacon.position.set(gatewayPosition.x, 0.98, gatewayPosition.z);
    scene.add(gatewayBeacon);
    horizontalRing(0.42, gatewayPosition.x, 0.035, gatewayPosition.z, 0.65);
    deviceLabel('GATEWAY', '#b8f46b', gatewayPosition.x, 1.45, gatewayPosition.z);
    box(0.85, 0.055, 0.58, displayPosition.x, 0.19, displayPosition.z + 0.19, nodeMetal);
    box(0.86, 0.55, 0.055, displayPosition.x, 0.5, displayPosition.z - 0.08, nodeBody);
    box(0.7, 0.4, 0.02, displayPosition.x, 0.51, displayPosition.z - 0.04, screen, false);
    deviceLabel('DISPLAY', '#ffffff', displayPosition.x, 1.12, displayPosition.z);
    const nodeGroup = groupSince(groupStart);

    // Keep the original simple silhouette geometry for both figures.
    const greenFigureMaterial = new THREE.MeshStandardMaterial({
      color: 0xb8f46b, emissive: 0xb8f46b, emissiveIntensity: 0.35,
      roughness: 0.5, transparent: true, opacity: 0.62, depthWrite: false
    });
    const whiteFigureMaterial = new THREE.MeshStandardMaterial({
      color: 0xffffff, emissive: 0xffffff, emissiveIntensity: 0.25,
      roughness: 0.5, transparent: true, opacity: 0.62, depthWrite: false
    });
    function makePresence(x, z, figureMaterial) {
      const presence = new THREE.Group();
      presence.position.set(x, 0, z);
      scene.add(presence);
      function figurePart(geometry, px, py, pz, rotationZ = 0) {
        const part = new THREE.Mesh(geometry, figureMaterial);
        part.position.set(px, py, pz);
        part.rotation.z = rotationZ;
        presence.add(part);
      }
      figurePart(new THREE.SphereGeometry(0.19, 20, 16), 0, 1.63, 0);
      figurePart(new THREE.CapsuleGeometry(0.22, 0.62, 6, 12), 0, 1.02, 0);
      figurePart(new THREE.CapsuleGeometry(0.065, 0.48, 4, 10), -0.33, 1.05, 0, -0.25);
      figurePart(new THREE.CapsuleGeometry(0.065, 0.48, 4, 10), 0.33, 1.05, 0, 0.25);
      figurePart(new THREE.CapsuleGeometry(0.085, 0.48, 4, 10), -0.13, 0.35, 0, -0.05);
      figurePart(new THREE.CapsuleGeometry(0.085, 0.48, 4, 10), 0.13, 0.35, 0, 0.05);
      return presence;
    }

    const people = [
      { x: -1.2, z: 0.75, color: 0xb8f46b, figureMaterial: greenFigureMaterial },
      { x: 2.2, z: 0.85, color: 0xffffff, figureMaterial: whiteFigureMaterial }
    ];
    people.forEach((person) => {
      person.figure = makePresence(person.x, person.z, person.figureMaterial);
      const volume = new THREE.Mesh(
        new THREE.CylinderGeometry(0.72, 1.06, 2.2, 48, 1, true),
        new THREE.MeshBasicMaterial({ color: person.color, transparent: true, opacity: 0.085,
          side: THREE.DoubleSide, depthWrite: false })
      );
      volume.position.set(person.x, 1.1, person.z);
      scene.add(volume);
      person.volume = volume;
      person.rings = [];
      for (const radius of [0.72, 1.05, 1.38]) {
        const ring = horizontalRing(radius, person.x, 0.045, person.z, 0.48 / radius, person.color);
        person.rings.push(ring);
      }
    });

    function flow(from, to, color, opacity, lift) {
      const curve = new THREE.CatmullRomCurve3([
        from.clone(),
        from.clone().lerp(to, 0.5).add(new THREE.Vector3(0, lift, 0)),
        to.clone()
      ]);
      const lineMaterial = new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0, depthWrite: false });
      scene.add(new THREE.Mesh(new THREE.TubeGeometry(curve, 36, 0.014, 6, false), lineMaterial));
      const packet = new THREE.Mesh(
        new THREE.SphereGeometry(0.055, 10, 8),
        new THREE.MeshBasicMaterial({ color, toneMapped: false })
      );
      scene.add(packet);
      return { curve, lineMaterial, packet, opacity };
    }

    const broadcastFlows = nodePositions.map((position) =>
      flow(senderPosition, position.clone().add(new THREE.Vector3(0, 0.22, 0)), 0xffffff, 0.55, 0.55)
    );
    const reportFlows = nodePositions.map((position) =>
      flow(position.clone().add(new THREE.Vector3(0, 0.22, 0)), gatewayPosition, 0xb8f46b, 0.55, 0.45)
    );
    const displayLine = new THREE.Line(
      new THREE.BufferGeometry().setFromPoints([gatewayPosition, displayPosition]),
      new THREE.LineDashedMaterial({ color: 0xffffff, transparent: true, opacity: 0, dashSize: 0.14, gapSize: 0.1 })
    );
    displayLine.computeLineDistances();
    scene.add(displayLine);

    const scanRing = new THREE.Mesh(
      new THREE.TorusGeometry(1, 0.018, 6, 96),
      new THREE.MeshBasicMaterial({ color: 0xb8f46b, transparent: true, opacity: 0, depthWrite: false })
    );
    scanRing.rotation.x = Math.PI / 2;
    scanRing.position.y = 0.065;
    scene.add(scanRing);

    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const introDuration = 3.15;
    const progress = (time, start, duration) => Math.min(1, Math.max(0, (time - start) / duration));
    const easeOut = (amount) => 1 - Math.pow(1 - amount, 3);
    const easeBack = (amount) => 1 + 2.70158 * Math.pow(amount - 1, 3) + 1.70158 * Math.pow(amount - 1, 2);

    function updateScene(time) {
      const floor = reducedMotion ? 1 : easeOut(progress(time, 0, 0.9));
      const walls = reducedMotion ? 1 : easeOut(progress(time, 0.25, 1.05));
      const nodes = reducedMotion ? 1 : easeBack(progress(time, 1.22, 0.78));
      const network = reducedMotion ? 1 : easeOut(progress(time, 1.62, 0.75));
      const signals = reducedMotion ? 1 : easeOut(progress(time, 2.05, 1.0));

      floorGroup.scale.set(0.72 + floor * 0.28, 1, 0.72 + floor * 0.28);
      floorGroup.position.y = -0.35 * (1 - floor);
      wallGroup.scale.y = Math.max(0.001, walls);
      furniturePieces.forEach(({ mesh, y }, index) => {
        const amount = reducedMotion ? 1 : easeBack(progress(time, 0.68 + index * 0.022, 0.68));
        mesh.scale.y = Math.max(0.001, amount);
        mesh.position.y = y - 0.22 * (1 - Math.min(1, amount));
      });
      nodeGroup.scale.y = Math.max(0.001, nodes);
      [...broadcastFlows, ...reportFlows].forEach(({ lineMaterial, opacity }) => { lineMaterial.opacity = opacity * network; });
      displayLine.material.opacity = 0.65 * network;

      const pulse = reducedMotion ? 1 : 1 + Math.sin(time * 1.45) * 0.045;
      people.forEach((person, index) => {
        const appearance = reducedMotion ? 1 : easeBack(progress(time, 1.72 + index * 0.15, 0.72));
        const field = reducedMotion ? 1 : easeOut(progress(time, 2.0 + index * 0.12, 0.78));
        person.figure.scale.setScalar(Math.max(0.001, appearance));
        person.volume.material.opacity = (reducedMotion ? 0.075 : 0.075 + Math.sin(time * 1.3 + index * 1.4) * 0.018) * field;
        person.rings.forEach((ring, ringIndex) => ring.scale.setScalar(Math.max(0.001, field * (pulse + ringIndex * 0.025))));
      });
      broadcastFlows.forEach(({ curve, packet }, index) => {
        packet.position.copy(curve.getPoint(reducedMotion ? 0.75 : (time * 0.19 + index * 0.23) % 1));
        packet.scale.setScalar(Math.max(0.001, signals));
      });
      reportFlows.forEach(({ curve, packet }, index) => {
        packet.position.copy(curve.getPoint(reducedMotion ? 0.75 : (time * 0.16 + index * 0.28) % 1));
        packet.scale.setScalar(Math.max(0.001, signals));
      });

      const sweep = reducedMotion ? 0 : progress(time, 1.55, 1.25);
      scanRing.scale.setScalar(0.2 + sweep * 5.8);
      scanRing.material.opacity = sweep > 0 && sweep < 1 ? 0.3 * Math.sin(Math.PI * sweep) : 0;
      camera.zoom = reducedMotion ? 1 : 0.86 + 0.14 * easeOut(progress(time, 0, 2.75));
      camera.updateProjectionMatrix();
      controls.enabled = reducedMotion || time >= introDuration;
      if (controls.enabled) stage.classList.add('scene-intro-complete');
    }

    updateScene(0);

    let framing = '';
    const resize = () => {
      const width = stage.clientWidth;
      const height = stage.clientHeight;
      if (!width || !height) return;
      const aspect = width / height;
      const nextFraming = aspect < 0.8 ? 'portrait' : aspect < 1.4 ? 'compact' : 'wide';
      if (nextFraming !== framing) {
        if (nextFraming === 'portrait') {
          camera.fov = 48;
          homePosition.set(16, 11.9, 17.2);
        } else if (nextFraming === 'compact') {
          camera.fov = 42;
          homePosition.set(12.3, 9.5, 13.3);
        } else {
          camera.fov = 32;
          homePosition.set(11.8, 9.4, 12.9);
        }
        camera.position.copy(homePosition);
        controls.update();
        framing = nextFraming;
      }
      camera.aspect = aspect;
      camera.updateProjectionMatrix();
      renderer.setSize(width, height, false);
      renderer.render(scene, camera);
    };
    const resizeObserver = new ResizeObserver(resize);
    resizeObserver.observe(stage);
    resize();

    resetButton?.addEventListener('click', () => {
      camera.position.copy(homePosition);
      controls.target.set(0, 1.1, 0);
      controls.update();
    });

    let visible = true;
    const visibilityObserver = new IntersectionObserver(([entry]) => {
      visible = entry.isIntersecting;
    }, { threshold: 0.01 });
    visibilityObserver.observe(stage);

    const clock = new THREE.Clock();
    function animate() {
      requestAnimationFrame(animate);
      if (!visible || document.hidden) return;
      const time = clock.getElapsedTime();
      updateScene(time);
      controls.update();
      renderer.render(scene, camera);
    }
    stage.classList.add('webgl-ready');
    animate();

    canvas.addEventListener('webglcontextlost', () => {
      stage.classList.remove('webgl-ready');
      stage.classList.add('webgl-failed');
    });
  } catch (error) {
    stage.classList.add('webgl-failed');
    console.warn('3D room unavailable.', error);
  }
}

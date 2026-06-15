import React, { useEffect, useRef } from "react";
import * as THREE from "three";

interface CoreParticleCanvasProps {
  status: string; // 'none' | 'new' | 'classifying' | 'retrieving' | 'generating' | 'evaluating' | 'auto_resolved' | 'assigned' | 'escalated'
  routingPath: string; // 'auto_resolved' | 'assigned' | 'escalated' | 'none'
  triggerDecompose?: boolean;
}

export default function CoreParticleCanvas({
  status = "none",
  routingPath = "none",
  triggerDecompose = false,
}: CoreParticleCanvasProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);

  // Three.js References
  const sceneRef = useRef<THREE.Scene | null>(null);
  const cameraRef = useRef<THREE.PerspectiveCamera | null>(null);
  const rendererRef = useRef<THREE.WebGLRenderer | null>(null);
  const particleGeometryRef = useRef<THREE.BufferGeometry | null>(null);
  const particleSystemRef = useRef<THREE.Points | null>(null);
  const animationFrameIdRef = useRef<number | null>(null);

  // State parameters for transition and decomposition
  const activeStateRef = useRef<"solid" | "decomposing" | "reassembling">("solid");
  const stateTimerRef = useRef<number>(0);
  const targetShapeRef = useRef<"sphere" | "clusters" | "funnel" | "galaxy" | "matrix" | "resolved_core" | "escalated_split" | "pipelines" | "scatter">("sphere");

  // Interaction vectors
  const mouseRef = useRef({ x: 0, y: 0, targetX: 0, targetY: 0 });

  // Handle Target Shape mapping based on pipeline state
  useEffect(() => {
    // When status changes, determine the target geometric layout
    if (status === "none" || status === "new") {
      targetShapeRef.current = "sphere";
    } else if (status === "classifying") {
      targetShapeRef.current = "clusters";
    } else if (status === "classified" || status === "retrieving") {
      targetShapeRef.current = "funnel";
    } else if (status === "generating") {
      targetShapeRef.current = "galaxy";
    } else if (status === "evaluating") {
      targetShapeRef.current = "matrix";
    } else if (status === "auto_resolved" || status === "resolved" || status === "closed") {
      targetShapeRef.current = "resolved_core";
    } else if (status === "assigned") {
      targetShapeRef.current = "pipelines";
    } else if (status === "escalated") {
      targetShapeRef.current = "escalated_split";
    } else {
      targetShapeRef.current = "sphere";
    }

    // Force a rapid "decomposition" explosion trigger phase whenever shape changes, followed by reassembly
    if (status !== "none") {
      activeStateRef.current = "decomposing";
      stateTimerRef.current = 0;
    }
  }, [status, routingPath]);

  // Handle explicit Decomposition click
  useEffect(() => {
    if (triggerDecompose) {
      activeStateRef.current = "decomposing";
      stateTimerRef.current = 0;
    }
  }, [triggerDecompose]);

  useEffect(() => {
    if (!containerRef.current || !canvasRef.current) return;

    const width = containerRef.current.clientWidth;
    const height = containerRef.current.clientHeight || 400;

    // 1. Scene setup
    const scene = new THREE.Scene();
    sceneRef.current = scene;

    // 2. Camera setup
    const camera = new THREE.PerspectiveCamera(60, width / height, 0.1, 100);
    camera.position.z = 22;
    cameraRef.current = camera;

    // 3. Renderer design
    const renderer = new THREE.WebGLRenderer({
      canvas: canvasRef.current,
      alpha: true,
      antialias: true,
      powerPreference: "high-performance",
    });
    renderer.setSize(width, height);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    rendererRef.current = renderer;

    // Add ambient lightning to boost highlights
    const ambientLight = new THREE.AmbientLight(0xffffff, 0.25);
    scene.add(ambientLight);

    const pointLight = new THREE.PointLight(0x00f0ff, 2, 80);
    pointLight.position.set(5, 5, 10);
    scene.add(pointLight);

    // 4. Custom Particle physics buffers
    const particleCount = 2800;
    const positions = new Float32Array(particleCount * 3);
    const colors = new Float32Array(particleCount * 3);

    // Track dynamic custom attributes for physics simulation
    const currentPositions = new Float32Array(particleCount * 3);
    const velocities = new Float32Array(particleCount * 3);
    const particleOriginalIndices = new Float32Array(particleCount);

    // Define helper coordinates for shapes initially
    for (let i = 0; i < particleCount; i++) {
      // Setup random positions in raw space initially
      const r = 10 + Math.random() * 5;
      const theta = Math.random() * Math.PI * 2;
      const phi = Math.acos(Math.random() * 2 - 1);

      const x = r * Math.sin(phi) * Math.cos(theta);
      const y = r * Math.sin(phi) * Math.sin(theta);
      const z = r * Math.cos(phi);

      positions[i * 3] = x;
      positions[i * 3 + 1] = y;
      positions[i * 3 + 2] = z;

      currentPositions[i * 3] = x;
      currentPositions[i * 3 + 1] = y;
      currentPositions[i * 3 + 2] = z;

      // Small randomized velocities
      velocities[i * 3] = (Math.random() - 0.5) * 0.1;
      velocities[i * 3 + 1] = (Math.random() - 0.5) * 0.1;
      velocities[i * 3 + 2] = (Math.random() - 0.5) * 0.1;

      particleOriginalIndices[i] = i;

      // Color maps
      colors[i * 3] = 0.0; // R
      colors[i * 3 + 1] = 0.94; // G
      colors[i * 3 + 2] = 1.0; // B
    }

    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute("position", new THREE.BufferAttribute(currentPositions, 3));
    geometry.setAttribute("color", new THREE.BufferAttribute(colors, 3));
    particleGeometryRef.current = geometry;

    // Beautiful glowing disc sprite structure
    const pMaterial = new THREE.PointsMaterial({
      size: 0.15,
      vertexColors: true,
      transparent: true,
      opacity: 0.9,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    });

    const particleSystem = new THREE.Points(geometry, pMaterial);
    scene.add(particleSystem);
    particleSystemRef.current = particleSystem;

    // 5. Generate Target Coordinates utility function
    const getTargetCoordinates = (i: number, shape: typeof targetShapeRef.current) => {
      const target = new THREE.Vector3();

      if (shape === "sphere") {
        // Standby System: concentric circular orbits spinning nicely
        const r = 6.5;
        const ringIndex = i % 3;
        const theta = (i / (particleCount / 3)) * Math.PI * 2;
        if (ringIndex === 0) {
          target.x = r * Math.cos(theta);
          target.y = r * Math.sin(theta);
          target.z = 0;
        } else if (ringIndex === 1) {
          target.x = r * Math.cos(theta);
          target.y = 0;
          target.z = r * Math.sin(theta);
        } else {
          target.x = 0;
          target.y = r * Math.cos(theta);
          target.z = r * Math.sin(theta);
        }
      } else if (shape === "clusters") {
        // AI Softmax Category Clouds in 3D Space
        const clusterId = i % 6;
        const rLocal = 1.0 + Math.random() * 0.8;
        const thetaLocal = Math.random() * Math.PI * 2;
        const phiLocal = Math.acos(Math.random() * 2 - 1);
        
        const offsets = [
          new THREE.Vector3(-6, 4, 0),   // Infrastructure
          new THREE.Vector3(6, 4, 0),    // Application
          new THREE.Vector3(-6, -4, 2),  // Security
          new THREE.Vector3(6, -4, -2),  // Database
          new THREE.Vector3(0, 5, -4),   // Storage
          new THREE.Vector3(0, -5, 4)    // Network
        ];
        const center = offsets[clusterId];
        target.x = center.x + rLocal * Math.sin(phiLocal) * Math.cos(thetaLocal);
        target.y = center.y + rLocal * Math.sin(phiLocal) * Math.sin(thetaLocal);
        target.z = center.z + rLocal * Math.cos(phiLocal);
      } else if (shape === "funnel") {
        // Deep whirlpool / vortex scanning query indexes
        const ratio = i / particleCount;
        const theta = ratio * Math.PI * 24;
        const rVal = 9.0 * (1.0 - ratio) + 0.5;
        const heightVal = 14.0 * ratio - 7.0;
        target.x = rVal * Math.cos(theta);
        target.y = heightVal;
        target.z = rVal * Math.sin(theta);
      } else if (shape === "galaxy") {
        // Logarithmic arm galaxy representing synthesis
        const arm = i % 2 === 0 ? 0 : 1;
        const deg = (i / particleCount) * Math.PI * 12;
        const rVal = 1.0 + 8.0 * (i / particleCount);
        const angle = deg + (arm === 0 ? 0 : Math.PI);
        target.x = rVal * Math.cos(angle) + (Math.random() - 0.5) * 0.4;
        target.y = (Math.random() - 0.5) * 1.0;
        target.z = rVal * Math.sin(angle) + (Math.random() - 0.5) * 0.4;
      } else if (shape === "matrix") {
        // Hypercube grid mesh validating outputs
        const gridSide = 14; 
        const indexX = i % gridSide;
        const indexY = Math.floor(i / gridSide) % gridSide;
        const indexZ = Math.floor(i / (gridSide * gridSide)) % gridSide;
        const spacing = 1.2;
        target.x = (indexX - gridSide / 2) * spacing;
        target.y = (indexY - gridSide / 2) * spacing;
        target.z = (indexZ - gridSide / 2) * spacing;
      } else if (shape === "resolved_core") {
        // Hyper-dense spinning emerald nucleus
        const theta = (i / particleCount) * Math.PI * 2;
        const r = 3.5 + Math.sin(i * 0.1) * 0.4;
        const spiralSpeed = 16;
        target.x = r * Math.cos(theta * spiralSpeed);
        target.y = r * Math.sin(theta * spiralSpeed) + Math.sin(theta) * 0.3;
        target.z = (Math.random() - 0.5) * 1.2;
      } else if (shape === "pipelines") {
        // Horizontal parallel dispatch lanes
        const lane = i % 3;
        const xProgress = ((i % Math.floor(particleCount / 3)) / (particleCount / 3)) * 24 - 12;
        target.x = xProgress;
        if (lane === 0) {
          target.y = 3.5;
          target.z = Math.sin(xProgress * 0.4) * 1.5;
        } else if (lane === 1) {
          target.y = 0;
          target.z = Math.cos(xProgress * 0.4) * 1.5;
        } else {
          target.y = -3.5;
          target.z = Math.sin(xProgress * 0.4 + Math.PI) * 1.5;
        }
      } else if (shape === "escalated_split") {
        // Opposing warning red fractured rings
        const ring = i % 2 === 0 ? 0 : 1;
        const theta = (i / particleCount) * Math.PI * 4;
        const r = 4.5;
        if (ring === 0) {
          target.x = r * Math.cos(theta) - 5;
          target.y = r * Math.sin(theta);
          target.z = Math.sin(theta * 3) * 1.5;
        } else {
          target.x = r * Math.cos(theta) + 5;
          target.y = Math.sin(theta) * 1.5;
          target.z = r * Math.sin(theta);
        }
      } else {
        target.x = (Math.random() - 0.5) * 30;
        target.y = (Math.random() - 0.5) * 30;
        target.z = (Math.random() - 0.5) * 20;
      }

      return target;
    };

    // Keep dynamic static targets in memory so we don't recalculate objects
    const targets = new Float32Array(particleCount * 3);
    const updateTargetCoords = () => {
      const shape = targetShapeRef.current;
      for (let i = 0; i < particleCount; i++) {
        const coord = getTargetCoordinates(i, shape);
        targets[i * 3] = coord.x;
        targets[i * 3 + 1] = coord.y;
        targets[i * 3 + 2] = coord.z;
      }
    };
    updateTargetCoords();

    let clock = new THREE.Clock();

    // 6. Physics Animation Loop
    const tick = () => {
      const elapsed = clock.getElapsedTime();
      stateTimerRef.current += 1;

      // Mouse response camera orbit
      mouseRef.current.x += (mouseRef.current.targetX - mouseRef.current.x) * 0.08;
      mouseRef.current.y += (mouseRef.current.targetY - mouseRef.current.y) * 0.08;

      camera.position.x = mouseRef.current.x * 12 + Math.sin(elapsed * 0.15) * 3;
      camera.position.y = mouseRef.current.y * 12 + Math.cos(elapsed * 0.15) * 2;
      camera.lookAt(new THREE.Vector3(0, 0, 0));

      const posAttr = geometry.getAttribute("position") as THREE.BufferAttribute;
      const colAttr = geometry.getAttribute("color") as THREE.BufferAttribute;

      const pArr = posAttr.array as Float32Array;
      const cArr = colAttr.array as Float32Array;

      // Handle transition states
      if (activeStateRef.current === "decomposing") {
        // High explosive push
        if (stateTimerRef.current === 1) {
          // Explode particles outward with randomized high speed vectors
          for (let i = 0; i < particleCount; i++) {
            const px = pArr[i * 3];
            const py = pArr[i * 3 + 1];
            const pz = pArr[i * 3 + 2];
            const len = Math.sqrt(px * px + py * py + pz * pz) || 1;

            velocities[i * 3] = (px / len) * 0.8 + (Math.random() - 0.5) * 0.5;
            velocities[i * 3 + 1] = (py / len) * 0.8 + (Math.random() - 0.5) * 0.5;
            velocities[i * 3 + 2] = (pz / len) * 0.8 + (Math.random() - 0.5) * 0.5;
          }
        }

        // Apply velocities with heavy turbulence and damping
        for (let i = 0; i < particleCount; i++) {
          pArr[i * 3] += velocities[i * 3];
          pArr[i * 3 + 1] += velocities[i * 3 + 1];
          pArr[i * 3 + 2] += velocities[i * 3 + 2];

          // Subside explosion force over time
          velocities[i * 3] *= 0.84;
          velocities[i * 3 + 1] *= 0.84;
          velocities[i * 3 + 2] *= 0.84;

          // Dynamically shift color into glowing magenta/orange sparkles during explosion
          cArr[i * 3] += (1.0 - cArr[i * 3]) * 0.1; // Turn red up
          cArr[i * 3 + 1] += (0.2 - cArr[i * 3 + 1]) * 0.1; // Green down
          cArr[i * 3 + 2] += (0.6 - cArr[i * 3 + 2]) * 0.1; // Blue medium-down
        }

        if (stateTimerRef.current > 24) {
          activeStateRef.current = "reassembling";
          stateTimerRef.current = 0;
          updateTargetCoords(); // precalculate targets
        }
      } else if (activeStateRef.current === "reassembling" || activeStateRef.current === "solid") {
        // Draw particles towards targets with gravitational pull
        const attractionStrength = activeStateRef.current === "reassembling" ? 0.08 : 0.04;
        const shape = targetShapeRef.current;

        for (let i = 0; i < particleCount; i++) {
          const tx = targets[i * 3];
          const ty = targets[i * 3 + 1];
          const tz = targets[i * 3 + 2];

          const dx = tx - pArr[i * 3];
          const dy = ty - pArr[i * 3 + 1];
          const dz = tz - pArr[i * 3 + 2];

          // Magnetic attraction + subtle orbital drift
          velocities[i * 3] = velocities[i * 3] * 0.75 + dx * attractionStrength;
          velocities[i * 3 + 1] = velocities[i * 3 + 1] * 0.75 + dy * attractionStrength;
          velocities[i * 3 + 2] = velocities[i * 3 + 2] * 0.75 + dz * attractionStrength;

          // Interactive magnetic repeller force when mouse is active
          if (mouseRef.current.x !== 0 || mouseRef.current.y !== 0) {
            const mx = mouseRef.current.x * 15;
            const my = mouseRef.current.y * 15;
            const rx = pArr[i * 3] - mx;
            const ry = pArr[i * 3 + 1] - my;
            const dist = Math.sqrt(rx * rx + ry * ry);
            if (dist < 4.0) {
              const repel = (4.0 - dist) * 0.12;
              velocities[i * 3] += (rx / dist) * repel;
              velocities[i * 3 + 1] += (ry / dist) * repel;
            }
          }

          pArr[i * 3] += velocities[i * 3];
          pArr[i * 3 + 1] += velocities[i * 3 + 1];
          pArr[i * 3 + 2] += velocities[i * 3 + 2];

          // Dynamic colors based on destination shape
          if (shape === "resolved_core") {
            // Intense elegant emerald Highlights
            cArr[i * 3] += (0.05 - cArr[i * 3]) * 0.12;     // R
            cArr[i * 3 + 1] += (0.95 - cArr[i * 3 + 1]) * 0.12; // G
            cArr[i * 3 + 2] += (0.45 - cArr[i * 3 + 2]) * 0.12; // B
          } else if (shape === "escalated_split") {
            // Intense Crimson warning signals
            cArr[i * 3] += (0.95 - cArr[i * 3]) * 0.12;
            cArr[i * 3 + 1] += (0.05 - cArr[i * 3 + 1]) * 0.12;
            cArr[i * 3 + 2] += (0.25 - cArr[i * 3 + 2]) * 0.12;
          } else if (shape === "clusters") {
            // Distinct multi-domain colors matching active domains
            const clusterId = i % 6;
            // 0: Blue, 1: Teal, 2: Rose, 3: Purple, 4: Amber, 5: Cyan
            const rMap = [0.1, 0.0, 0.9, 0.6, 0.9, 0.0];
            const gMap = [0.4, 0.8, 0.1, 0.2, 0.6, 0.7];
            const bMap = [0.9, 0.7, 0.3, 0.9, 0.1, 0.9];
            cArr[i * 3] += (rMap[clusterId] - cArr[i * 3]) * 0.12;
            cArr[i * 3 + 1] += (gMap[clusterId] - cArr[i * 3 + 1]) * 0.12;
            cArr[i * 3 + 2] += (bMap[clusterId] - cArr[i * 3 + 2]) * 0.12;
          } else if (shape === "funnel") {
            // Dynamic golden amber to deep orange funnel
            const depth = (i % 10) / 10.0;
            cArr[i * 3] += (0.95 - cArr[i * 3]) * 0.12;
            cArr[i * 3 + 1] += ((0.4 + depth * 0.45) - cArr[i * 3 + 1]) * 0.12;
            cArr[i * 3 + 2] += (0.1 - cArr[i * 3 + 2]) * 0.12;
          } else if (shape === "galaxy") {
            // Swirling magenta/violet/indigo blend
            const spiralColorMix = (i % 2 === 0);
            if (spiralColorMix) {
              cArr[i * 3] += (0.85 - cArr[i * 3]) * 0.12;
              cArr[i * 3 + 1] += (0.05 - cArr[i * 3 + 1]) * 0.12;
              cArr[i * 3 + 2] += (0.95 - cArr[i * 3 + 2]) * 0.12;
            } else {
              cArr[i * 3] += (0.05 - cArr[i * 3]) * 0.12;
              cArr[i * 3 + 1] += (0.75 - cArr[i * 3 + 1]) * 0.12;
              cArr[i * 3 + 2] += (0.95 - cArr[i * 3 + 2]) * 0.12;
            }
          } else if (shape === "matrix") {
            // Highly ordered deep violet lattice
            cArr[i * 3] += (0.45 - cArr[i * 3]) * 0.12;
            cArr[i * 3 + 1] += (0.25 - cArr[i * 3 + 1]) * 0.12;
            cArr[i * 3 + 2] += (0.95 - cArr[i * 3 + 2]) * 0.12;
          } else if (shape === "pipelines") {
            // 3 lanes: Green resolved path, Blue standard dispatch, and Red escalated path
            const lane = i % 3;
            if (lane === 0) { // Auto-solved path (Emerald Green)
              cArr[i * 3] += (0.05 - cArr[i * 3]) * 0.12;
              cArr[i * 3 + 1] += (0.95 - cArr[i * 3 + 1]) * 0.12;
              cArr[i * 3 + 2] += (0.45 - cArr[i * 3 + 2]) * 0.12;
            } else if (lane === 1) { // Standard dispatch pipeline (Cyan Sky Blue)
              cArr[i * 3] += (0.0 - cArr[i * 3]) * 0.12;
              cArr[i * 3 + 1] += (0.75 - cArr[i * 3 + 1]) * 0.12;
              cArr[i * 3 + 2] += (0.95 - cArr[i * 3 + 2]) * 0.12;
            } else { // Critical backup pipeline (Gold Amber Alert)
              cArr[i * 3] += (0.95 - cArr[i * 3]) * 0.12;
              cArr[i * 3 + 1] += (0.55 - cArr[i * 3 + 1]) * 0.12;
              cArr[i * 3 + 2] += (0.05 - cArr[i * 3 + 2]) * 0.12;
            }
          } else {
            // Standby beautiful neon sky cyan coordinates
            cArr[i * 3] += (0.0 - cArr[i * 3]) * 0.12;
            cArr[i * 3 + 1] += (0.85 - cArr[i * 3 + 1]) * 0.12;
            cArr[i * 3 + 2] += (1.0 - cArr[i * 3 + 2]) * 0.12;
          }
        }

        if (activeStateRef.current === "reassembling" && stateTimerRef.current > 35) {
          activeStateRef.current = "solid";
        }
      }

      // Slow orbital rotate core
      particleSystem.rotation.y = elapsed * 0.12;
      particleSystem.rotation.z = elapsed * 0.05;

      posAttr.needsUpdate = true;
      colAttr.needsUpdate = true;

      renderer.render(scene, camera);
      animationFrameIdRef.current = requestAnimationFrame(tick);
    };

    tick();

    // 7. Dynamic Sizing
    const resizeObserver = new ResizeObserver((entries) => {
      if (!entries || entries.length === 0) return;
      const { width: newWidth, height: newHeight } = entries[0].contentRect;
      const roundedHeight = newHeight || 400;

      if (cameraRef.current && rendererRef.current) {
        cameraRef.current.aspect = newWidth / roundedHeight;
        cameraRef.current.updateProjectionMatrix();
        rendererRef.current.setSize(newWidth, roundedHeight);
      }
    });
    resizeObserver.observe(containerRef.current);

    // Mouse listener inside component wrapper boundaries
    const handleMouseMove = (e: MouseEvent) => {
      const rect = canvasRef.current?.getBoundingClientRect();
      if (!rect) return;
      const x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
      const y = -((e.clientY - rect.top) / rect.height) * 2 + 1;
      mouseRef.current.targetX = x * 0.5;
      mouseRef.current.targetY = y * 0.5;
    };

    const handleMouseLeave = () => {
      mouseRef.current.targetX = 0;
      mouseRef.current.targetY = 0;
    };

    canvasRef.current.addEventListener("mousemove", handleMouseMove);
    canvasRef.current.addEventListener("mouseleave", handleMouseLeave);

    return () => {
      resizeObserver.disconnect();
      if (canvasRef.current) {
        canvasRef.current.removeEventListener("mousemove", handleMouseMove);
        canvasRef.current.removeEventListener("mouseleave", handleMouseLeave);
      }
      if (animationFrameIdRef.current) {
        cancelAnimationFrame(animationFrameIdRef.current);
      }
      if (rendererRef.current) {
        rendererRef.current.dispose();
      }
      // Purge structures
      while (scene.children.length > 0) {
        const obj = scene.children[0];
        scene.remove(obj);
        if (obj instanceof THREE.Points) {
          obj.geometry.dispose();
          (obj.material as THREE.Material).dispose();
        }
      }
    };
  }, []);

  return (
    <div
      ref={containerRef}
      className="relative w-full h-full min-h-[400px] md:min-h-[500px] overflow-hidden rounded-3xl cursor-grab active:cursor-grabbing select-none"
    >
      <canvas ref={canvasRef} className="absolute inset-0 block w-full h-full" />

      {/* Decorative HUD Details */}
      <div className="absolute top-4 left-4 flex flex-col gap-1 pointer-events-none">
        <span className="text-[10px] uppercase font-mono tracking-widest text-cyan-400 font-bold flex items-center gap-1.5 bg-black/40 border border-white/5 backdrop-blur px-2.5 py-1 rounded-md">
          <span className="w-1.5 h-1.5 rounded-full bg-cyan-400 animate-ping"></span>
          AUTONOMOUS PARTICLE FIELD
        </span>
        <span className="text-[9px] font-mono text-slate-500 uppercase tracking-widest ml-1">
          WebGL Renderer Array Enabled (2,800 Nodes)
        </span>
      </div>

      <div className="absolute bottom-4 right-4 bg-black/50 border border-white/5 backdrop-blur px-3 py-1.5 rounded-lg text-right pointer-events-none">
        <div className="text-[9px] uppercase font-mono text-slate-500 tracking-widest">
          INTERACTIVE ORIENTATION
        </div>
        <div className="text-[10px] font-mono font-medium text-slate-300 uppercase tracking-wider">
          Drag to pivot holographic core
        </div>
      </div>
    </div>
  );
}

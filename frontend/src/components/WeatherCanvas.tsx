import React, { useEffect, useRef, useState } from "react";
import * as THREE from "three";

interface WeatherCanvasProps {
  theme: string; // 'cyber-rain' | 'solar-flare' | 'neon-nebula' | 'grid-overcast' | 'cryo-snow' | 'plasma-storm'
  isInteractive: boolean;
}

export default function WeatherCanvas({ theme = "cyber-rain", isInteractive = true }: WeatherCanvasProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);

  // Keep references to ThreeJS objects to manipulate across theme updates
  const sceneRef = useRef<THREE.Scene | null>(null);
  const cameraRef = useRef<THREE.PerspectiveCamera | null>(null);
  const rendererRef = useRef<THREE.WebGLRenderer | null>(null);
  const particleSystemRef = useRef<THREE.Points | null>(null);
  const lineSystemRef = useRef<THREE.LineSegments | null>(null);
  const secondarySystemRef = useRef<THREE.Mesh | THREE.Points | null>(null);
  const animationFrameIdRef = useRef<number | null>(null);

  // Keep track of interaction states
  const mouseRef = useRef({ x: 0, y: 0, targetX: 0, targetY: 0 });
  const isDragging = useRef(false);
  const prevMousePosition = useRef({ x: 0, y: 0 });
  const rotationParams = useRef({ x: 0, y: 0 });

  useEffect(() => {
    if (!containerRef.current || !canvasRef.current) return;

    // 1. Initial Setup
    const width = containerRef.current.clientWidth;
    const height = containerRef.current.clientHeight || 350;

    const scene = new THREE.Scene();
    sceneRef.current = scene;

    const camera = new THREE.PerspectiveCamera(60, width / height, 0.1, 100);
    camera.position.z = 25;
    cameraRef.current = camera;

    const renderer = new THREE.WebGLRenderer({
      canvas: canvasRef.current,
      alpha: true,
      antialias: true,
      powerPreference: "high-performance",
    });
    renderer.setSize(width, height);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    rendererRef.current = renderer;

    // 2. Add light
    const ambientLight = new THREE.AmbientLight(0xffffff, 0.4);
    scene.add(ambientLight);

    const pointLight = new THREE.PointLight(0x00f0ff, 1.5, 50);
    pointLight.position.set(10, 10, 10);
    scene.add(pointLight);

    // 3. Render loop variables
    let clock = new THREE.Clock();

    // 4. Initialize weather assets based on theme
    recreateWeatherAssets(theme, scene);

    // 5. Animation loop
    const tick = () => {
      const elapsedTime = clock.getElapsedTime();

      // Smooth mouse rotation camera response
      if (isInteractive) {
        // Damp positions
        mouseRef.current.x += (mouseRef.current.targetX - mouseRef.current.x) * 0.05;
        mouseRef.current.y += (mouseRef.current.targetY - mouseRef.current.y) * 0.05;

        camera.position.x = mouseRef.current.x * 6 + Math.sin(elapsedTime * 0.15) * 2;
        camera.position.y = mouseRef.current.y * 6 + Math.cos(elapsedTime * 0.15) * 1;
        camera.lookAt(new THREE.Vector3(0, 0, 0));
      }

      // Unique custom weather animation dynamics
      animateWeather(theme, elapsedTime);

      renderer.render(scene, camera);
      animationFrameIdRef.current = requestAnimationFrame(tick);
    };

    tick();

    // 6. Responsive Sizing with ResizeObserver
    const resizeObserver = new ResizeObserver((entries) => {
      if (!entries || entries.length === 0) return;
      const { width: newWidth, height: newHeight } = entries[0].contentRect;
      
      const roundedHeight = newHeight || 350;
      if (cameraRef.current && rendererRef.current) {
        cameraRef.current.aspect = newWidth / roundedHeight;
        cameraRef.current.updateProjectionMatrix();
        rendererRef.current.setSize(newWidth, roundedHeight);
      }
    });
    resizeObserver.observe(containerRef.current);

    // Cleanup inside hook
    return () => {
      resizeObserver.disconnect();
      if (animationFrameIdRef.current) {
        cancelAnimationFrame(animationFrameIdRef.current);
      }
      // dispose of ThreeJS structures cleanly
      if (rendererRef.current) {
        rendererRef.current.dispose();
      }
      clearScene(scene);
    };
  }, [theme]); // Re-run when theme changes to reload appropriate visual systems

  // Re-emit mouse coordinate movements for aesthetic interactive orbit
  const handleMouseMove = (e: React.MouseEvent) => {
    if (!containerRef.current || !isInteractive) return;

    if (isDragging.current) {
      const deltaX = e.clientX - prevMousePosition.current.x;
      const deltaY = e.clientY - prevMousePosition.current.y;
      
      rotationParams.current.y += deltaX * 0.01;
      rotationParams.current.x += deltaY * 0.01;

      mouseRef.current.targetX = rotationParams.current.y;
      mouseRef.current.targetY = rotationParams.current.x;

      prevMousePosition.current = { x: e.clientX, y: e.clientY };
    } else {
      const rect = containerRef.current.getBoundingClientRect();
      const x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
      const y = -((e.clientY - rect.top) / rect.height) * 2 + 1;
      mouseRef.current.targetX = x * 0.5;
      mouseRef.current.targetY = y * 0.5;
    }
  };

  const handleMouseDown = (e: React.MouseEvent) => {
    isDragging.current = true;
    prevMousePosition.current = { x: e.clientX, y: e.clientY };
  };

  const handleMouseUp = () => {
    isDragging.current = false;
  };

  const handleMouseLeave = () => {
    isDragging.current = false;
    mouseRef.current.targetX = 0;
    mouseRef.current.targetY = 0;
  };

  // Helper routine to fully purge elements
  function clearScene(scene: THREE.Scene) {
    while (scene.children.length > 0) {
      const object = scene.children[0];
      scene.remove(object);
      if (object instanceof THREE.Mesh) {
        object.geometry.dispose();
        if (Array.isArray(object.material)) {
          object.material.forEach((mat) => mat.dispose());
        } else {
          object.material.dispose();
        }
      } else if (object instanceof THREE.Points) {
        object.geometry.dispose();
        (object.material as THREE.Material).dispose();
      } else if (object instanceof THREE.LineSegments) {
        object.geometry.dispose();
        (object.material as THREE.Material).dispose();
      }
    }
    particleSystemRef.current = null;
    lineSystemRef.current = null;
    secondarySystemRef.current = null;
  }

  // Generate appropriate geometer structures on state modification
  function recreateWeatherAssets(currentTheme: string, scene: THREE.Scene) {
    clearScene(scene);

    const count = currentTheme === "neon-nebula" ? 4000 : currentTheme === "cyber-rain" ? 1500 : 1000;
    const positions = new Float32Array(count * 3);
    const colors = new Float32Array(count * 3);

    // Theme variations setup
    if (currentTheme === "cyber-rain") {
      // Fast dropping neon lines
      const linePositions = new Float32Array(count * 6); // start and end points for lines
      const lineColors = new Float32Array(count * 6);

      for (let i = 0; i < count; i++) {
        const x = (Math.random() - 0.5) * 35;
        const y = Math.random() * 30 - 15;
        const z = (Math.random() - 0.5) * 20;

        linePositions[i * 6] = x;
        linePositions[i * 6 + 1] = y;
        linePositions[i * 6 + 2] = z;

        // rain ray extends slightly downward
        linePositions[i * 6 + 3] = x;
        linePositions[i * 6 + 4] = y - 1.5;
        linePositions[i * 6 + 5] = z;

        // Cyan blue lines
        lineColors[i * 6] = 0.0;
        lineColors[i * 6 + 1] = 0.85;
        lineColors[i * 6 + 2] = 1.0;

        lineColors[i * 6 + 3] = 0.0;
        lineColors[i * 6 + 4] = 0.2;
        lineColors[i * 6 + 5] = 0.5;
      }

      const lineGeo = new THREE.BufferGeometry();
      lineGeo.setAttribute("position", new THREE.BufferAttribute(linePositions, 3));
      lineGeo.setAttribute("color", new THREE.BufferAttribute(lineColors, 3));

      const lineMat = new THREE.LineBasicMaterial({
        vertexColors: true,
        transparent: true,
        opacity: 0.75,
        blending: THREE.AdditiveBlending,
      });

      const lineSystem = new THREE.LineSegments(lineGeo, lineMat);
      scene.add(lineSystem);
      lineSystemRef.current = lineSystem;

    } else if (currentTheme === "solar-flare") {
      // central glowing sun sphere
      const sphereGeo = new THREE.SphereGeometry(4, 32, 32);
      const sphereMat = new THREE.MeshBasicMaterial({
        color: 0xff4f00,
        wireframe: true,
        transparent: true,
        opacity: 0.15,
        blending: THREE.AdditiveBlending,
      });
      const sunMesh = new THREE.Mesh(sphereGeo, sphereMat);
      scene.add(sunMesh);
      secondarySystemRef.current = sunMesh;

      // halo orbits
      for (let i = 0; i < count; i++) {
        const theta = Math.random() * Math.PI * 2;
        const phi = Math.acos(Math.random() * 2 - 1);
        const distance = 4.5 + Math.random() * 5; // shell distance

        positions[i * 3] = distance * Math.sin(phi) * Math.cos(theta);
        positions[i * 3 + 1] = distance * Math.sin(phi) * Math.sin(theta);
        positions[i * 3 + 2] = distance * Math.cos(phi);

        // solar fiery colors (orange to bright neon yellow)
        colors[i * 3] = 1.0;
        colors[i * 3 + 1] = 0.3 + Math.random() * 0.7;
        colors[i * 3 + 2] = 0.0;
      }

      const pointsGeo = new THREE.BufferGeometry();
      pointsGeo.setAttribute("position", new THREE.BufferAttribute(positions, 3));
      pointsGeo.setAttribute("color", new THREE.BufferAttribute(colors, 3));

      const pointsMat = new THREE.PointsMaterial({
        size: 0.14,
        vertexColors: true,
        transparent: true,
        opacity: 0.9,
        blending: THREE.AdditiveBlending,
      });

      const points = new THREE.Points(pointsGeo, pointsMat);
      scene.add(points);
      particleSystemRef.current = points;

    } else if (currentTheme === "neon-nebula") {
      // Swirling cosmic galaxy coordinates
      for (let i = 0; i < count; i++) {
        const angle = Math.random() * Math.PI * 2;
        const radius = 1 + Math.pow(Math.random(), 2) * 15;
        const spiral = angle + radius * 0.3; // spiral twist

        positions[i * 3] = Math.cos(spiral) * radius + (Math.random() - 0.5) * 1.5;
        positions[i * 3 + 1] = (Math.random() - 0.5) * 3; // vertical thickness
        positions[i * 3 + 2] = Math.sin(spiral) * radius + (Math.random() - 0.5) * 1.5;

        // deep cosmic palettes (magenta pinks to deep ultraviolet)
        const mixture = Math.random();
        if (mixture < 0.5) {
          // Purple
          colors[i * 3] = 0.54;
          colors[i * 3 + 1] = 0.0;
          colors[i * 3 + 2] = 1.0;
        } else {
          // Neon pink
          colors[i * 3] = 1.0;
          colors[i * 3 + 1] = 0.0;
          colors[i * 3 + 2] = 0.5;
        }
      }

      const pointsGeo = new THREE.BufferGeometry();
      pointsGeo.setAttribute("position", new THREE.BufferAttribute(positions, 3));
      pointsGeo.setAttribute("color", new THREE.BufferAttribute(colors, 3));

      const pointsMat = new THREE.PointsMaterial({
        size: 0.12,
        vertexColors: true,
        transparent: true,
        opacity: 0.8,
        blending: THREE.AdditiveBlending,
      });

      const points = new THREE.Points(pointsGeo, pointsMat);
      scene.add(points);
      particleSystemRef.current = points;

    } else if (currentTheme === "grid-overcast") {
      // Horizontal digital scans + drifting low clouds
      const gridHelper = new THREE.GridHelper(50, 20, 0x00f0ff, 0x112233);
      gridHelper.position.y = -6;
      gridHelper.rotation.x = 0.1;
      scene.add(gridHelper);
      secondarySystemRef.current = (gridHelper as any);

      // cloud dust drifting on top of the plain
      for (let i = 0; i < count; i++) {
        positions[i * 3] = (Math.random() - 0.5) * 40;
        positions[i * 3 + 1] = -5 + Math.random() * 8; // low clouds
        positions[i * 3 + 2] = (Math.random() - 0.5) * 20;

        // digital green/teal colors
        colors[i * 3] = 0.0;
        colors[i * 3 + 1] = 1.0;
        colors[i * 3 + 2] = Math.random() * 0.6 + 0.4;
      }

      const pointsGeo = new THREE.BufferGeometry();
      pointsGeo.setAttribute("position", new THREE.BufferAttribute(positions, 3));
      pointsGeo.setAttribute("color", new THREE.BufferAttribute(colors, 3));

      const pointsMat = new THREE.PointsMaterial({
        size: 0.16,
        vertexColors: true,
        transparent: true,
        opacity: 0.5,
        blending: THREE.AdditiveBlending,
      });

      const points = new THREE.Points(pointsGeo, pointsMat);
      scene.add(points);
      particleSystemRef.current = points;

    } else if (currentTheme === "cryo-snow") {
      // floating stars, snowflakes waving slowly
      for (let i = 0; i < count; i++) {
        positions[i * 3] = (Math.random() - 0.5) * 35;
        positions[i * 3 + 1] = Math.random() * 30 - 15;
        positions[i * 3 + 2] = (Math.random() - 0.5) * 20;

        // pastel ice coordinates (crisp bright neon pink-white to cold turquoise)
        const mixture = Math.random();
        if (mixture < 0.4) {
          // icy cyan
          colors[i * 3] = 0.0;
          colors[i * 3 + 1] = 0.95;
          colors[i * 3 + 2] = 0.95;
        } else if (mixture < 0.7) {
          // pure crystal white
          colors[i * 3] = 1.0;
          colors[i * 3 + 1] = 1.0;
          colors[i * 3 + 2] = 1.0;
        } else {
          // cryo-pink
          colors[i * 3] = 1.0;
          colors[i * 3 + 1] = 0.2;
          colors[i * 3 + 2] = 0.75;
        }
      }

      const pointsGeo = new THREE.BufferGeometry();
      pointsGeo.setAttribute("position", new THREE.BufferAttribute(positions, 3));
      pointsGeo.setAttribute("color", new THREE.BufferAttribute(colors, 3));

      const pointsMat = new THREE.PointsMaterial({
        size: 0.18,
        vertexColors: true,
        transparent: true,
        opacity: 0.85,
        blending: THREE.AdditiveBlending,
      });

      const points = new THREE.Points(pointsGeo, pointsMat);
      scene.add(points);
      particleSystemRef.current = points;

    } else {
      // plasma-storm: rapid discharges + chaotic orbiting static
      const lightningGeo = new THREE.BufferGeometry();
      const strikePoints = new Float32Array(15 * 3); // lightning segments
      lightningGeo.setAttribute("position", new THREE.BufferAttribute(strikePoints, 3));
      const lightningMat = new THREE.LineBasicMaterial({
        color: 0xff00ff,
        linewidth: 2,
        transparent: true,
        opacity: 0,
      });
      const strikeSegs = new THREE.LineSegments(lightningGeo, lightningMat);
      scene.add(strikeSegs);
      secondarySystemRef.current = strikeSegs;

      // background static dust
      for (let i = 0; i < count; i++) {
        positions[i * 3] = (Math.random() - 0.5) * 35;
        positions[i * 3 + 1] = (Math.random() - 0.5) * 25;
        positions[i * 3 + 2] = (Math.random() - 0.5) * 20;

        // stormy deep colors (electric pinks, glowing highlights, dark dusts)
        const rnd = Math.random();
        if (rnd < 0.5) {
          // vibrant electric violet
          colors[i * 3] = 0.8;
          colors[i * 3 + 1] = 0.0;
          colors[i * 3 + 2] = 1.0;
        } else {
          // high strike yellow
          colors[i * 3] = 1.0;
          colors[i * 3 + 1] = 0.9;
          colors[i * 3 + 2] = 0.0;
        }
      }

      const pointsGeo = new THREE.BufferGeometry();
      pointsGeo.setAttribute("position", new THREE.BufferAttribute(positions, 3));
      pointsGeo.setAttribute("color", new THREE.BufferAttribute(colors, 3));

      const pointsMat = new THREE.PointsMaterial({
        size: 0.15,
        vertexColors: true,
        transparent: true,
        opacity: 0.9,
        blending: THREE.AdditiveBlending,
      });

      const points = new THREE.Points(pointsGeo, pointsMat);
      scene.add(points);
      particleSystemRef.current = points;
    }
  }

  // Update position attributes and matrices according to physical weather dynamics on clock tick
  function animateWeather(currentTheme: string, time: number) {
    if (currentTheme === "cyber-rain" && lineSystemRef.current) {
      const geo = lineSystemRef.current.geometry;
      const positions = geo.getAttribute("position") as THREE.BufferAttribute;
      const array = positions.array as Float32Array;
      const count = array.length / 6;

      for (let i = 0; i < count; i++) {
        // Drop start and end y
        array[i * 6 + 1] -= 0.65; // speed
        array[i * 6 + 4] -= 0.65;

        // If bottomed out, reset
        if (array[i * 6 + 1] < -15) {
          const x = (Math.random() - 0.5) * 35;
          const z = (Math.random() - 0.5) * 20;
          array[i * 6] = x;
          array[i * 6 + 1] = 15;
          array[i * 6 + 2] = z;

          array[i * 6 + 3] = x;
          array[i * 6 + 4] = 13.5;
          array[i * 6 + 5] = z;
        }
      }
      positions.needsUpdate = true;

    } else if (currentTheme === "solar-flare" && particleSystemRef.current) {
      // rotate solar orbits
      particleSystemRef.current.rotation.y = time * 0.25;
      particleSystemRef.current.rotation.x = time * 0.1;

      // pulsing expand solar scale wave
      const scale = 1 + Math.sin(time * 2) * 0.08;
      particleSystemRef.current.scale.set(scale, scale, scale);

      if (secondarySystemRef.current && secondarySystemRef.current instanceof THREE.Mesh) {
        secondarySystemRef.current.rotation.y = time * -0.15;
        secondarySystemRef.current.rotation.z = time * 0.25;
      }

    } else if (currentTheme === "neon-nebula" && particleSystemRef.current) {
      // Swirl around vortex
      particleSystemRef.current.rotation.y = time * 0.08;
      const geo = particleSystemRef.current.geometry;
      const positions = geo.getAttribute("position") as THREE.BufferAttribute;
      const array = positions.array as Float32Array;
      const count = array.length / 3;

      for (let i = 0; i < count; i++) {
        // wavy nebula shift
        array[i * 3 + 1] += Math.sin(time + array[i * 3]) * 0.005;
      }
      positions.needsUpdate = true;

    } else if (currentTheme === "grid-overcast" && particleSystemRef.current) {
      // Drift cloud dust horizontally
      const geo = particleSystemRef.current.geometry;
      const positions = geo.getAttribute("position") as THREE.BufferAttribute;
      const array = positions.array as Float32Array;
      const count = array.length / 3;

      for (let i = 0; i < count; i++) {
        array[i * 3] += 0.03; // move right
        if (array[i * 3] > 20) {
          array[i * 3] = -20;
        }
        // light undulating wave
        array[i * 3 + 1] += Math.cos(time * 0.5 + array[i * 3]) * 0.01;
      }
      positions.needsUpdate = true;

      // slide grid
      if (secondarySystemRef.current) {
        secondarySystemRef.current.position.z = (time * 4) % 2.5;
      }

    } else if (currentTheme === "cryo-snow" && particleSystemRef.current) {
      const geo = particleSystemRef.current.geometry;
      const positions = geo.getAttribute("position") as THREE.BufferAttribute;
      const array = positions.array as Float32Array;
      const count = array.length / 3;

      for (let i = 0; i < count; i++) {
        array[i * 3 + 1] -= 0.06; // fall speed
        // drift sideways sinusoidally
        array[i * 3] += Math.sin(time * 0.8 + i) * 0.015;

        // Reset if bottomed out
        if (array[i * 3 + 1] < -15) {
          array[i * 3] = (Math.random() - 0.5) * 35;
          array[i * 3 + 1] = 15;
          array[i * 3 + 2] = (Math.random() - 0.5) * 20;
        }
      }
      positions.needsUpdate = true;

    } else if (currentTheme === "plasma-storm" && particleSystemRef.current) {
      // chaotic rotation
      particleSystemRef.current.rotation.y = time * 0.6;
      particleSystemRef.current.rotation.z = time * 0.2;

      // simulate rapid lightning triggers
      if (secondarySystemRef.current && secondarySystemRef.current instanceof THREE.LineSegments) {
        const lightning = secondarySystemRef.current;
        const geo = lightning.geometry;
        const positions = geo.getAttribute("position") as THREE.BufferAttribute;
        const array = positions.array as Float32Array;
        const mat = lightning.material as THREE.LineBasicMaterial;

        // random flash threshold
        if (Math.random() > 0.94) {
          mat.opacity = 0.9;
          
          let curX = (Math.random() - 0.5) * 10;
          let curY = 12;
          let curZ = (Math.random() - 0.5) * 5;

          // Build zigzag chain down to ground
          for (let i = 0; i < 15; i++) {
            array[i * 3] = curX;
            array[i * 3 + 1] = curY;
            array[i * 3 + 2] = curZ;

            // Offset next joint
            curX += (Math.random() - 0.5) * 4;
            curY -= 1.8;
            curZ += (Math.random() - 0.5) * 2;
          }
          positions.needsUpdate = true;
        } else {
          mat.opacity -= 0.15; // decay rapidly
          if (mat.opacity < 0) mat.opacity = 0;
        }
      }
    }
  }

  return (
    <div
      ref={containerRef}
      className="relative w-full h-full min-h-[350px] overflow-hidden rounded-2xl cursor-grab active:cursor-grabbing select-none"
      onMouseMove={handleMouseMove}
      onMouseDown={handleMouseDown}
      onMouseUp={handleMouseUp}
      onMouseLeave={handleMouseLeave}
    >
      <canvas ref={canvasRef} className="absolute inset-0 block w-full h-full" />
      <div className="absolute top-3 left-3 flex gap-2">
        <span className="glass-pill px-2.5 py-0.5 text-[10px] uppercase font-mono tracking-wider text-neon-blue rounded border border-white/5 bg-black/40">
          WebGL: active
        </span>
        <span className="glass-pill px-2.5 py-0.5 text-[10px] uppercase font-mono tracking-wider text-neon-pink rounded border border-white/5 bg-black/40">
          {theme}
        </span>
      </div>
      <div className="absolute bottom-3 right-3 text-[10px] font-mono tracking-widest text-[#94a3b8]/50 select-none uppercase">
        Drag to inspect vector field
      </div>
    </div>
  );
}

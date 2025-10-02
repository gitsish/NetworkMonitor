(function(){
  const container = document.getElementById('globeViz');

  // Create renderer, scene, camera
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.setSize(window.innerWidth, window.innerHeight);
  container.appendChild(renderer.domElement);

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(40, window.innerWidth / window.innerHeight, 0.1, 1000);
  camera.position.z = 2.3;

  // Globe from three-globe
  const Globe = window.Globe;
  const globe = new Globe()
    .globeImageUrl('//unpkg.com/three-globe/example/img/earth-blue-marble.jpg')
    .bumpImageUrl('//unpkg.com/three-globe/example/img/earth-topology.png')
    .backgroundImageUrl('//unpkg.com/three-globe/example/img/night-sky.png')
    .showAtmosphere(true)
    .atmosphereColor('#00bfff')
    .atmosphereAltitude(0.12);

  scene.add(globe);

  // Lighting
  const ambientLight = new THREE.AmbientLight(0xbbddff, 0.6);
  scene.add(ambientLight);
  const dirLight = new THREE.DirectionalLight(0xffffff, 0.6);
  dirLight.position.set(5, 3, 5);
  scene.add(dirLight);

  // Data centers (simplified)
  const dataCenters = [
    { lat: 37.7749, lng: -122.4194, size: 0.02 },
    { lat: 40.7128, lng: -74.0060, size: 0.018 },
    { lat: 51.5074, lng: -0.1278, size: 0.017 },
    { lat: 35.6762, lng: 139.6503, size: 0.021 },
    { lat: 1.3521, lng: 103.8198, size: 0.018 },
    { lat: -33.8688, lng: 151.2093, size: 0.015 },
    { lat: 31.2304, lng: 121.4737, size: 0.02 },
    { lat: 28.6139, lng: 77.2090, size: 0.016 },
    { lat: 19.0760, lng: 72.8777, size: 0.017 }
  ];

  globe
    .pointsData(dataCenters)
    .pointLat('lat')
    .pointLng('lng')
    .pointRadius('size')
    .pointAltitude(0.01)
    .pointColor(() => 'rgba(0,191,255,0.95)')
    .pointResolution(12);

  // Generate random connections
  function generateConnections(num=30){
    const conns = [];
    for(let i=0;i<num;i++){
      const a = dataCenters[Math.floor(Math.random()*dataCenters.length)];
      let b = dataCenters[Math.floor(Math.random()*dataCenters.length)];
      if(a === b){ b = dataCenters[(dataCenters.indexOf(a)+1) % dataCenters.length]; }
      conns.push({
        startLat: a.lat, startLng: a.lng,
        endLat: b.lat, endLng: b.lng,
        color: ['#00bfff','#00ffff','#0080ff'][Math.floor(Math.random()*3)]
      });
    }
    return conns;
  }

  let currentConnections = generateConnections(30);

  globe
    .arcsData(currentConnections)
    .arcStartLat('startLat')
    .arcStartLng('startLng')
    .arcEndLat('endLat')
    .arcEndLng('endLng')
    .arcColor('color')
    .arcAltitude(0.25)
    .arcStroke(0.6)
    .arcDashLength(0.4)
    .arcDashGap(0.2)
    .arcDashAnimateTime(2000)
    .arcsTransitionDuration(0);

  globe
    .ringsData(dataCenters)
    .ringLat('lat')
    .ringLng('lng')
    .ringMaxRadius('size')
    .ringPropagationSpeed(2)
    .ringRepeatPeriod(1500)
    .ringColor(() => 'rgba(0,191,255,0.35)');

  // Controls (auto-rotate, prevent zoom)
  const controls = new THREE.OrbitControls(camera, renderer.domElement);
  controls.autoRotate = true;
  controls.autoRotateSpeed = 0.4;
  controls.enableZoom = false;
  controls.enablePan = false;
  controls.enableRotate = true;

  // Resize handling
  window.addEventListener('resize', () => {
    const W = window.innerWidth, H = window.innerHeight;
    renderer.setSize(W, H);
    camera.aspect = W / H;
    camera.updateProjectionMatrix();
  });

  // Refresh arcs periodically
  setInterval(() => {
    currentConnections = generateConnections(28);
    globe.arcsData(currentConnections);
  }, 3000);

  // Render loop
  (function animate(){
    controls.update();
    renderer.render(scene, camera);
    requestAnimationFrame(animate);
  })();
})();

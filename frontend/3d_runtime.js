(() => {
  let canvas = document.getElementById('miku-3d-canvas');
  const layer = document.getElementById('miku-3d-layer');
  const displayArea = document.getElementById('miku-display');
  const status = document.getElementById('miku-3d-status');
  const adjustToggle = document.getElementById('character-adjust-toggle');
  const adjustDismiss = document.getElementById('character-adjust-dismiss');
  const ipcRenderer = window.miku?.ipc;

  let renderer;
  let scene;
  let camera;
  let mmdModel;
  let live2dApp;
  let live2dModel;
  let frameId;
  let requestedMode = 'media';
  let selectedModelId = '';
  let loading = false;
  let generation = 0;
  let yawTarget = 0;
  let resizeHandler;
  let live2dFraming = { horizontalOffset: 0 };
  let adjustmentEnabled = false;
  let dragState;
  let saveViewTimer;
  let characterViews = readCharacterViews();

  const LIVE2D_FRAMING = Object.freeze({
    // This model has substantial transparent space on its left side. Preserve
    // a general bounds-based frame while compensating for that source layout.
    '玄宝 Miku/miku/miku.model3.json': { horizontalOffset: -0.24 },
  });

  // The bundled model explicitly supports disabling its default watermark.
  // These are its watermark, hotkey hint, attribution, and reference layers.
  const LIVE2D_HIDDEN_OVERLAY_PARTS = Object.freeze([
    'Part18', 'Part17', 'Part77', 'PartSketch0',
  ]);

  function setStatus(message) {
    if (status) status.textContent = message;
  }

  function clamp(value, minimum, maximum) {
    return Math.min(Math.max(value, minimum), maximum);
  }

  function normalizeView(view) {
    return {
      x: Number.isFinite(view?.x) ? clamp(view.x, -1, 1) : 0,
      y: Number.isFinite(view?.y) ? clamp(view.y, -1, 1) : 0,
      scale: Number.isFinite(view?.scale) ? clamp(view.scale, 0.5, 3) : 1,
    };
  }

  function readCharacterViews() {
    const saved = ipcRenderer?.sendSync?.('get-config', 'miku-character-view');
    if (!saved || typeof saved !== 'object' || Array.isArray(saved)) return {};
    return Object.fromEntries(Object.entries(saved).map(([modelId, view]) => [modelId, normalizeView(view)]));
  }

  function currentView() {
    const saved = characterViews[selectedModelId];
    if (saved) return saved;
    const view = normalizeView();
    characterViews[selectedModelId] = view;
    return view;
  }

  function saveCharacterViews() {
    window.clearTimeout(saveViewTimer);
    saveViewTimer = undefined;
    ipcRenderer?.send?.('set-config', { key: 'miku-character-view', val: characterViews });
  }

  function scheduleCharacterViewSave() {
    window.clearTimeout(saveViewTimer);
    saveViewTimer = window.setTimeout(saveCharacterViews, 180);
  }

  function updateAdjustmentButton() {
    adjustToggle?.setAttribute('aria-pressed', String(adjustmentEnabled));
    layer?.classList.toggle('is-adjusting', adjustmentEnabled);
    displayArea?.classList.toggle('is-adjusting-model', adjustmentEnabled);
  }

  function setAdjustment(enabled) {
    adjustmentEnabled = Boolean(enabled);
    dragState = undefined;
    updateAdjustmentButton();
  }

  function applyMmdView() {
    if (!mmdModel || !camera) return;
    const view = currentView();
    mmdModel.position.x = view.x * 20;
    camera.position.z = 34 / view.scale;
  }

  function bindAdjustmentEvents(view) {
    view.addEventListener('mousedown', (event) => {
      if (!adjustmentEnabled) return;
      event.preventDefault();
      event.stopPropagation();
    });
    view.addEventListener('pointerdown', (event) => {
      if (!adjustmentEnabled || event.button !== 0) return;
      event.preventDefault();
      event.stopPropagation();
      dragState = {
        pointerId: event.pointerId,
        clientX: event.clientX,
        clientY: event.clientY,
        view: { ...currentView() },
      };
      view.setPointerCapture?.(event.pointerId);
    });
    view.addEventListener('pointermove', (event) => {
      if (!dragState || event.pointerId !== dragState.pointerId) return;
      event.preventDefault();
      event.stopPropagation();
      const width = Math.max(view.clientWidth, 1);
      const height = Math.max(view.clientHeight, 1);
      const modelView = currentView();
      modelView.x = clamp(dragState.view.x + (event.clientX - dragState.clientX) / width, -1, 1);
      modelView.y = clamp(dragState.view.y + (event.clientY - dragState.clientY) / height, -1, 1);
      fitLive2D();
      applyMmdView();
    });
    const finishDrag = (event) => {
      if (!dragState || event.pointerId !== dragState.pointerId) return;
      event.preventDefault();
      event.stopPropagation();
      if (view.hasPointerCapture?.(event.pointerId)) view.releasePointerCapture(event.pointerId);
      dragState = undefined;
      saveCharacterViews();
    };
    view.addEventListener('pointerup', finishDrag);
    view.addEventListener('pointercancel', finishDrag);
    view.addEventListener('wheel', (event) => {
      if (!adjustmentEnabled) return;
      event.preventDefault();
      event.stopPropagation();
      const modelView = currentView();
      modelView.scale = clamp(modelView.scale * Math.exp(-event.deltaY * 0.001), 0.5, 3);
      fitLive2D();
      applyMmdView();
      scheduleCharacterViewSave();
    }, { passive: false });
  }

  function createRenderCanvas() {
    const nextCanvas = document.createElement('canvas');
    nextCanvas.id = 'miku-3d-canvas';
    nextCanvas.setAttribute('aria-hidden', 'true');
    if (canvas?.parentNode) {
      canvas.parentNode.replaceChild(nextCanvas, canvas);
    } else {
      layer?.insertBefore(nextCanvas, status || null);
    }
    canvas = nextCanvas;
    bindAdjustmentEvents(nextCanvas);
    return nextCanvas;
  }

  function clearRuntime() {
    generation += 1;
    if (frameId) cancelAnimationFrame(frameId);
    frameId = undefined;
    if (resizeHandler) window.removeEventListener('resize', resizeHandler);
    resizeHandler = undefined;
    const oldRenderer = renderer;
    const oldLive2dApp = live2dApp;
    renderer = scene = camera = mmdModel = live2dApp = live2dModel = undefined;
    loading = false;
    layer?.classList.remove('has-model');
    try {
      oldRenderer?.dispose();
      oldRenderer?.forceContextLoss?.();
    } catch (error) {
      console.warn('Failed to dispose previous MMD renderer:', error);
    }
    try {
      oldLive2dApp?.destroy(true, { children: true, texture: true, baseTexture: true });
    } catch (error) {
      console.warn('Failed to dispose previous Live2D renderer:', error);
    }
  }

  async function getSelectedModel() {
    const models = await ipcRenderer.invoke('list-character-models');
    if (!Array.isArray(models) || !models.length) return null;
    const availableIds = new Set(models.map((model) => model.id));
    for (const modelId of Object.keys(characterViews)) {
      if (!availableIds.has(modelId)) delete characterViews[modelId];
    }
    const selected = models.find((model) => model.id === selectedModelId) || models[0];
    selectedModelId = selected.id;
    return selected;
  }

  function fitLive2D() {
    if (!live2dApp || !live2dModel || !canvas || live2dApp.renderer.destroyed) return;
    const width = Math.max(canvas.clientWidth, 1);
    const height = Math.max(canvas.clientHeight, 1);
    live2dApp.renderer.resize(width, height);
    const bounds = live2dModel.getLocalBounds();
    const naturalWidth = Math.max(bounds.width, 1);
    const naturalHeight = Math.max(bounds.height, 1);
    // Frame roughly the top half of a standing model. Bounds are used instead
    // of the model canvas so asymmetric hair/accessories stay visually centered.
    const baseScale = Math.max(width / naturalWidth * 1.1, height / naturalHeight * 2.35);
    const view = currentView();
    live2dModel.scale.set(baseScale * view.scale);
    live2dModel.pivot.set(0, 0);
    live2dModel.position.set(0, 0);

    // The model's logical canvas is often wider than the painted character.
    // Align using the rendered bounds so the visible figure, rather than its
    // transparent margins, is centered in the pet window.
    const renderedBounds = live2dModel.getBounds();
    live2dModel.x = width / 2 - (renderedBounds.x + renderedBounds.width / 2)
      + width * (live2dFraming.horizontalOffset + view.x);
    live2dModel.y = height * (0.06 + view.y) - renderedBounds.y;
  }

  async function loadLive2D(entry, token, view) {
    if (!window.PIXI?.live2d?.Live2DModel || !window.Live2DCubismCore) {
      throw new Error('Live2D runtime dependency was not loaded');
    }
    setStatus('正在加载 Live2D 模型...');
    const response = await fetch(entry.url);
    if (!response.ok) throw new Error(`Unable to read model manifest (${response.status})`);
    const manifest = await response.json();
    if (token !== generation || requestedMode !== '3d') return;

    const motions = Array.isArray(entry.motions) ? entry.motions : [];
    const expressions = Array.isArray(entry.expressions) ? entry.expressions : [];
    manifest.url = entry.url;
    manifest.FileReferences = manifest.FileReferences || {};
    manifest.FileReferences.Motions = {
      ...(manifest.FileReferences.Motions || {}),
      ...(motions.length ? { Idle: motions.map((motion) => ({ File: motion.url })) } : {}),
    };
    manifest.FileReferences.Expressions = expressions.map((expression) => ({
      Name: expression.name.replace(/\.exp3\.json$/i, ''),
      File: expression.url,
    }));

    const app = new window.PIXI.Application({
      view,
      width: Math.max(view.clientWidth || 1, 1),
      height: Math.max(view.clientHeight || 1, 1),
      backgroundColor: 0xffffff,
      backgroundAlpha: 1,
      antialias: true,
      autoDensity: true,
      resolution: Math.min(window.devicePixelRatio || 1, 2),
    });
    const model = await window.PIXI.live2d.Live2DModel.from(manifest, {
      autoInteract: false,
      autoUpdate: true,
    });
    if (token !== generation || requestedMode !== '3d') {
      model.destroy();
      app.destroy(false, { children: true });
      return;
    }
    live2dApp = app;
    live2dModel = model;
    live2dFraming = LIVE2D_FRAMING[entry.id] || { horizontalOffset: 0 };
    app.stage.addChild(model);
    // Keep source assets intact and disable the model's opt-out watermark
    // layers in memory on every frame, so motions cannot restore them.
    const coreModel = model.internalModel?.coreModel;
    const hideDefaultWatermark = () => {
      coreModel?.setParameterValueById?.('Param137', 0);
      for (const partId of LIVE2D_HIDDEN_OVERLAY_PARTS) {
        coreModel?.setPartOpacityById?.(partId, 0);
      }
    };
    app.ticker.add(hideDefaultWatermark);
    hideDefaultWatermark();
    fitLive2D();
    resizeHandler = fitLive2D;
    window.addEventListener('resize', resizeHandler, { passive: true });
    layer?.classList.add('has-model');
    console.info('[Character] Live2D model loaded:', entry.name);
  }

  async function loadMmd(entry, token, view) {
    setStatus('正在加载 MMD 模型...');
    const [{ WebGLRenderer, Scene, PerspectiveCamera, AmbientLight, DirectionalLight, Clock }, { MMDLoader }] = await Promise.all([
      import('./node_modules/three/build/three.module.js'),
      import('./node_modules/three/examples/jsm/loaders/MMDLoader.js'),
    ]);
    if (token !== generation || requestedMode !== '3d') return;

    renderer = new WebGLRenderer({ canvas: view, alpha: false, antialias: true, powerPreference: 'low-power' });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.setClearColor(0xffffff, 1);
    scene = new Scene();
    camera = new PerspectiveCamera(28, 1, 0.1, 1000);
    camera.position.set(0, 10, 34);
    scene.add(new AmbientLight(0xffffff, 1.7));
    const keyLight = new DirectionalLight(0xffffff, 1.4);
    keyLight.position.set(5, 12, 14);
    scene.add(keyLight);

    const loader = new MMDLoader();
    loader.load(entry.url, (loadedModel) => {
      if (token !== generation || requestedMode !== '3d') return;
      mmdModel = loadedModel;
      mmdModel.position.set(0, -13, 0);
      mmdModel.rotation.y = Math.PI;
      scene.add(mmdModel);
      applyMmdView();
      layer?.classList.add('has-model');
      console.info('[Character] MMD model loaded:', entry.name);
      const clock = new Clock();
      const draw = () => {
        if (token !== generation || requestedMode !== '3d' || !renderer || !scene || !camera || !mmdModel) return;
        const width = Math.max(view.clientWidth, 1);
        const height = Math.max(view.clientHeight, 1);
        renderer.setSize(width, height, false);
        camera.aspect = width / height;
        camera.updateProjectionMatrix();
        const elapsed = clock.getElapsedTime();
        mmdModel.position.y = -13 + currentView().y * 20 + Math.sin(elapsed * 1.5) * 0.12;
        mmdModel.rotation.y += (Math.PI + yawTarget - mmdModel.rotation.y) * 0.035;
        renderer.render(scene, camera);
        frameId = requestAnimationFrame(draw);
      };
      draw();
    }, undefined, (error) => {
      console.error('Failed to load MMD model:', error);
      setStatus('MMD 模型加载失败，请检查纹理目录和模型许可。');
    });
  }

  async function loadModel() {
    if (loading || requestedMode !== '3d') return;
    loading = true;
    const token = generation;
    try {
      const entry = await getSelectedModel();
      if (token !== generation || requestedMode !== '3d') return;
      if (!entry) {
        setStatus('未找到模型。请放入 miku/models/<模型名>/。');
        return;
      }
      const view = createRenderCanvas();
      if (entry.type === 'live2d') await loadLive2D(entry, token, view);
      else await loadMmd(entry, token, view);
    } catch (error) {
      console.error('Character renderer initialization failed:', error);
      setStatus('模型渲染不可用，请查看启动器日志。');
    } finally {
      if (token === generation) loading = false;
    }
  }

  function chooseExpression(emotion) {
    const available = live2dModel?.internalModel?.motionManager?.expressionManager;
    if (!available) return;
    if (emotion === 'neutral') {
      available.resetExpression();
      return;
    }
    const candidates = {
      happy: ['比心', '葱'],
      sadness: ['圈圈'],
      surprise: ['QQ'],
      anger: ['葱'],
      fear: ['脸红'],
      disgust: ['前倾'],
      contempt: ['唱歌'],
    }[emotion] || [];
    const name = available.definitions?.find((expression) => (
      candidates.some((candidate) => expression.Name?.includes(candidate))
    ))?.Name;
    if (name) live2dModel.expression(name).catch((error) => console.warn('Live2D expression failed:', error));
  }

  window.Miku3D = Object.freeze({
    setMode(mode) {
      const nextMode = mode === '3d' ? '3d' : 'media';
      if (nextMode === requestedMode && (loading || renderer || live2dApp)) return;
      if (nextMode !== '3d') setAdjustment(false);
      requestedMode = nextMode;
      clearRuntime();
      if (requestedMode === '3d') loadModel();
    },
    setModel(modelId) {
      const nextId = typeof modelId === 'string' ? modelId : '';
      if (nextId === selectedModelId && (loading || renderer || live2dApp)) return;
      selectedModelId = nextId;
      if (requestedMode === '3d') {
        clearRuntime();
        loadModel();
      }
    },
    toggleAdjustment() {
      setAdjustment(!adjustmentEnabled);
    },
    exitAdjustment() {
      setAdjustment(false);
    },
    setEmotion(emotion) {
      const offsets = {
        happy: -0.16, surprise: 0.18, anger: 0.12, sadness: -0.1,
        fear: 0.2, disgust: -0.14, contempt: 0.1, neutral: 0,
      };
      yawTarget = offsets[emotion] || 0;
      chooseExpression(emotion);
    },
  });

  adjustToggle?.addEventListener('click', (event) => {
    event.preventDefault();
    event.stopPropagation();
    window.Miku3D.toggleAdjustment();
  });
  adjustDismiss?.addEventListener('click', (event) => {
    event.preventDefault();
    event.stopPropagation();
    window.Miku3D.exitAdjustment();
  });
  updateAdjustmentButton();
})();

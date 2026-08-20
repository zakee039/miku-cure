(() => {
  let canvas = document.getElementById('miku-3d-canvas');
  const layer = document.getElementById('miku-3d-layer');
  const displayArea = document.getElementById('miku-display');
  const status = document.getElementById('miku-3d-status');
  const feedToggle = document.getElementById('character-feed-toggle');
  const adjustToggle = document.getElementById('character-adjust-toggle');
  const adjustDismiss = document.getElementById('character-adjust-dismiss');
  const ipcRenderer = window.miku?.ipc;

  let renderer;
  let scene;
  let camera;
  let mmdModel;
  let mmdFrame;
  let mmdKeyLight;
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
  let actionTimer;
  let interactionMotion = { name: '', until: 0 };
  let musicActionActive = false;
  let interactionPointer;
  let clickTimer;
  let circleTrace;
  let hideModelWatermark = ipcRenderer?.sendSync?.('get-config', 'miku-hide-model-watermark') !== false;
  let watermarkParameterIds = new Set();
  let watermarkPartIds = [];
  let watermarkTickerBound = false;
  let activeActionParameters = {};
  let characterViews = readCharacterViews();

  const LIVE2D_FRAMING = Object.freeze({
    // This model has substantial transparent space on its left side. Preserve
    // a general bounds-based frame while compensating for that source layout.
    '玄宝 Miku/miku/miku.model3.json': {
      horizontalOffset: -0.24,
      // Preserve enough of the torso to keep the hands visible. This model's
      // hand poses extend substantially farther than its idle silhouette.
      verticalFill: 1.5,
      actionVerticalFill: { heart: 1.25, feed: 1.32, sing: 1.36 },
      hitAreas: [
        { name: 'head', left: 0.31, right: 0.69, top: 0.06, bottom: 0.27 },
        { name: 'face', left: 0.32, right: 0.68, top: 0.27, bottom: 0.52 },
        { name: 'arm', left: 0.05, right: 0.38, top: 0.48, bottom: 0.98 },
        { name: 'arm', left: 0.62, right: 0.95, top: 0.48, bottom: 0.98 },
      ],
    },
  });

  const WATERMARK_EXPRESSION_NAME = /(?:watermark|水印)/i;
  const LIVE2D_WATERMARK_PARTS = Object.freeze([
    'Part18', 'Part17', 'Part77', 'PartSketch0',
  ]);
  const LIVE2D_ACTIONS = Object.freeze({
    feed: { expression: /^(?:葱|大葱)$/i, duration: 3200 },
    sing: { expression: /^唱歌$/i, duration: 0 },
    heart: { expression: /^比心$/i, duration: 3600 },
    lean: { expression: /^前倾$/i, duration: 2200 },
    size: { expression: /^(?:QQ人|大小变)$/i, duration: 2600 },
    dizzy: { expression: /^(?:圈圈|晕晕)$/i, duration: 3600 },
    cry: { expression: /^(?:哭哭|哭泣|QQ人)$/i, duration: 5200 },
    blush: { expression: /^脸红$/i, duration: 2600 },
  });
  const XUANBAO_MIKU_ACTION_PARAMETERS = Object.freeze({
    feed: { Param133: 1, Param134: 0, Param135: 0 },
    sing: { Param133: 0, Param134: 1, Param135: 0 },
    heart: { Param133: 0, Param134: 0, Param135: 1 },
    lean: { Param132: 1 },
    blush: { Param130: 1 },
    dizzy: { Param125: 1 },
    cry: { Param131: 1, Param136: 1 },
  });

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
    const frame = mmdFrame || {
      baseX: 0, baseY: -13, targetX: 0, targetY: 10, targetZ: 0,
      distance: 34, xRange: 20, yRange: 20,
    };
    mmdModel.position.x = frame.baseX + view.x * frame.xRange;
    mmdModel.position.y = frame.baseY - view.y * frame.yRange;
    camera.position.set(frame.targetX, frame.targetY, frame.targetZ + frame.distance / view.scale);
    camera.lookAt(frame.targetX, frame.targetY, frame.targetZ);
    if (mmdKeyLight) {
      mmdKeyLight.position.copy(camera.position);
      mmdKeyLight.position.y += frame.yRange * 0.25;
      mmdKeyLight.target.position.set(frame.targetX, frame.targetY, frame.targetZ);
      mmdKeyLight.target.updateMatrixWorld();
    }
  }

  function resetAction() {
    window.clearTimeout(actionTimer);
    actionTimer = undefined;
    interactionMotion = { name: '', until: 0 };
    activeActionParameters = {};
    live2dModel?.internalModel?.motionManager?.expressionManager?.resetExpression?.();
    fitLive2D();
    if (musicActionActive) performAction('sing');
  }

  function findExpression(pattern) {
    return live2dModel?.internalModel?.motionManager?.expressionManager?.definitions?.find((expression) => (
      pattern.test(expression.Name || '')
    ));
  }

  function performAction(action) {
    if (!live2dModel || !action || requestedMode !== '3d') return false;
    const definition = LIVE2D_ACTIONS[action];
    if (!definition) return false;
    const expression = findExpression(definition.expression);
    if (!expression) return false;
    window.clearTimeout(actionTimer);
    interactionMotion = { name: action, until: definition.duration ? Date.now() + definition.duration : 0 };
    activeActionParameters = selectedModelId === '玄宝 Miku/miku/miku.model3.json'
      ? XUANBAO_MIKU_ACTION_PARAMETERS[action] || {}
      : {};
    live2dModel.expression(expression.Name).catch((error) => {
      console.warn(`Live2D action failed: ${action}`, error);
    });
    fitLive2D();
    if (definition.duration) {
      actionTimer = window.setTimeout(resetAction, definition.duration);
    }
    return true;
  }

  function getLive2DHitArea(clientX, clientY) {
    if (!live2dModel || !canvas) return '';
    const rect = canvas.getBoundingClientRect();
    const localX = clientX - rect.left;
    const localY = clientY - rect.top;
    const bounds = live2dModel.getBounds();
    if (!bounds.width || !bounds.height
      || localX < bounds.x || localX > bounds.x + bounds.width
      || localY < bounds.y || localY > bounds.y + bounds.height) return '';
    const x = (localX - bounds.x) / bounds.width;
    const y = (localY - bounds.y) / bounds.height;
    const hitAreas = live2dFraming.hitAreas;
    if (Array.isArray(hitAreas)) {
      return hitAreas.find((area) => (
        x >= area.left && x <= area.right && y >= area.top && y <= area.bottom
      ))?.name || '';
    }
    if (y < 0.38 && x > 0.27 && x < 0.73) return y < 0.25 ? 'head' : 'face';
    if (y > 0.3 && y < 0.78 && (x < 0.22 || x > 0.78)) return 'arm';
    return '';
  }

  function applyLive2DOverrides() {
    const coreModel = live2dModel?.internalModel?.coreModel;
    if (!coreModel) return;
    for (const parameterId of watermarkParameterIds) {
      coreModel.setParameterValueById?.(parameterId, hideModelWatermark ? 0 : 1);
    }
    for (const partId of watermarkPartIds) {
      coreModel.setPartOpacityById?.(partId, hideModelWatermark ? 0 : 1);
    }
    // Expressions use additive values and this model's idle update runs from
    // PIXI's shared ticker. Write after that update so hand poses stay active.
    for (const [parameterId, value] of Object.entries(activeActionParameters)) {
      coreModel.setParameterValueById?.(parameterId, value);
    }
  }

  function trackCircle(event) {
    if (!live2dModel || adjustmentEnabled || requestedMode !== '3d') return;
    const rect = canvas.getBoundingClientRect();
    const centerX = rect.left + rect.width / 2;
    const centerY = rect.top + rect.height / 2;
    const angle = Math.atan2(event.clientY - centerY, event.clientX - centerX);
    const radius = Math.hypot(event.clientX - centerX, event.clientY - centerY);
    if (radius < Math.min(rect.width, rect.height) * 0.17) return;
    const now = performance.now();
    if (!circleTrace || now - circleTrace.lastTime > 900) {
      circleTrace = { lastAngle: angle, turns: 0, lastTime: now, startedAt: now };
      return;
    }
    let delta = angle - circleTrace.lastAngle;
    if (delta > Math.PI) delta -= Math.PI * 2;
    if (delta < -Math.PI) delta += Math.PI * 2;
    circleTrace.turns += Math.abs(delta) / (Math.PI * 2);
    circleTrace.lastAngle = angle;
    circleTrace.lastTime = now;
    if (circleTrace.turns >= 3 && now - circleTrace.startedAt <= 7000) {
      performAction('dizzy');
      noteInteraction();
      circleTrace = undefined;
    }
  }

  let lastInteractionAt = Date.now();
  let idleReactionShown = false;

  function noteInteraction() {
    lastInteractionAt = Date.now();
    idleReactionShown = false;
  }

  window.setInterval(() => {
    if (!live2dModel || requestedMode !== '3d' || adjustmentEnabled || idleReactionShown) return;
    if (Date.now() - lastInteractionAt >= 30 * 60 * 1000) {
      idleReactionShown = performAction('cry');
    }
  }, 60 * 1000);

  function frameMmdUpperBody(Box3, Vector3) {
    if (!mmdModel || !camera) return;
    mmdModel.updateMatrixWorld(true);
    const bounds = new Box3().setFromObject(mmdModel);
    const size = bounds.getSize(new Vector3());
    const center = bounds.getCenter(new Vector3());
    if (!Number.isFinite(size.x) || !Number.isFinite(size.y) || size.x <= 0 || size.y <= 0) return;

    // Keep the upper 70% of differently sized PMX models inside the pet window.
    const visibleHeight = size.y * 0.76;
    const targetY = bounds.max.y - size.y * 0.33;
    mmdFrame = {
      baseX: mmdModel.position.x,
      baseY: mmdModel.position.y,
      targetX: center.x,
      targetY,
      targetZ: center.z,
      distance: visibleHeight / (2 * Math.tan(camera.fov * Math.PI / 360)),
      xRange: Math.max(size.x * 0.5, 1),
      yRange: Math.max(size.y * 0.5, 1),
    };
  }

  function tuneMmdMaterials(model) {
    model.traverse((object) => {
      if (!object.isMesh) return;
      const materials = Array.isArray(object.material) ? object.material : [object.material];
      for (const material of materials) {
        if (!material) continue;
        material.color?.multiplyScalar?.(0.82);
        material.emissive?.multiplyScalar?.(0.25);
        if ('emissiveIntensity' in material) material.emissiveIntensity = 0.5;
        material.needsUpdate = true;
      }
    });
  }

  function bindAdjustmentEvents(view) {
    view.addEventListener('mousedown', (event) => {
      // The canvas is reserved for model interactions. Window dragging starts
      // from the blank space in the top control bar above this layer.
      event.preventDefault();
      event.stopPropagation();
    });
    view.addEventListener('pointerdown', (event) => {
      if (!adjustmentEnabled && live2dModel && event.button === 0
        && getLive2DHitArea(event.clientX, event.clientY)) {
        interactionPointer = {
          pointerId: event.pointerId,
          clientX: event.clientX,
          clientY: event.clientY,
          moved: false,
        };
        return;
      }
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
      if (!adjustmentEnabled && live2dModel && interactionPointer?.pointerId === event.pointerId) {
        trackCircle(event);
        if (interactionPointer?.pointerId === event.pointerId
          && Math.hypot(event.clientX - interactionPointer.clientX, event.clientY - interactionPointer.clientY) > 8) {
          interactionPointer.moved = true;
        }
      }
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
    view.addEventListener('pointerup', (event) => {
      if (!interactionPointer || event.pointerId !== interactionPointer.pointerId) return;
      const pointer = interactionPointer;
      interactionPointer = undefined;
      if (pointer.moved || adjustmentEnabled) return;
      const action = { head: 'lean', face: 'blush', arm: 'heart' }[
        getLive2DHitArea(event.clientX, event.clientY)
      ];
      if (!action) return;
      window.clearTimeout(clickTimer);
      clickTimer = window.setTimeout(() => {
        if (performAction(action)) noteInteraction();
      }, 220);
    });
    view.addEventListener('dblclick', (event) => {
      if (adjustmentEnabled || !live2dModel) return;
      event.preventDefault();
      event.stopPropagation();
      window.clearTimeout(clickTimer);
      if (performAction('size')) noteInteraction();
    });
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
    if (watermarkTickerBound) {
      window.PIXI?.Ticker?.shared?.remove(applyLive2DOverrides);
      watermarkTickerBound = false;
    }
    const oldRenderer = renderer;
    const oldLive2dApp = live2dApp;
    renderer = scene = camera = mmdModel = mmdFrame = mmdKeyLight = live2dApp = live2dModel = undefined;
    watermarkParameterIds = new Set();
    watermarkPartIds = [];
    loading = false;
    resetAction();
    circleTrace = undefined;
    layer?.classList.remove('has-model');
    layer?.classList.remove('has-live2d');
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
    const selected = models.find((model) => model.id === selectedModelId)
      || models.find((model) => model.type === 'live2d')
      || models[0];
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
    // Frame the upper body. Bounds are used instead of the model canvas so
    // asymmetric hair/accessories stay visually centered.
    const baseScale = Math.max(
      width / naturalWidth * 1.1,
      height / naturalHeight * (
        live2dFraming.actionVerticalFill?.[interactionMotion.name]
        || live2dFraming.verticalFill
        || 2.35
      ),
    );
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

  async function getWatermarkParameterIds(expressions) {
    const watermarkExpressions = expressions.filter((expression) => (
      WATERMARK_EXPRESSION_NAME.test(expression.name)
    ));
    const definitions = await Promise.all(watermarkExpressions.map(async (expression) => {
      try {
        const response = await fetch(expression.url);
        return response.ok ? response.json() : null;
      } catch (error) {
        console.warn('Unable to read Live2D watermark expression:', error);
        return null;
      }
    }));
    return new Set(definitions.flatMap((definition) => (
      Array.isArray(definition?.Parameters)
        ? definition.Parameters.map((parameter) => parameter?.Id).filter((id) => typeof id === 'string')
        : []
    )));
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
    const nextWatermarkParameterIds = await getWatermarkParameterIds(expressions);
    if (token !== generation || requestedMode !== '3d') return;
    watermarkParameterIds = nextWatermarkParameterIds;
    watermarkPartIds = entry.id === '玄宝 Miku/miku/miku.model3.json'
      ? LIVE2D_WATERMARK_PARTS
      : [];
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
    // Respect model-provided watermark controls without modifying source assets.
    // Reapply after every model update so motions cannot re-enable the setting.
    window.PIXI.Ticker.shared.add(
      applyLive2DOverrides,
      undefined,
      window.PIXI.UPDATE_PRIORITY?.LOW ?? -25,
    );
    watermarkTickerBound = true;
    applyLive2DOverrides();
    fitLive2D();
    resizeHandler = fitLive2D;
    window.addEventListener('resize', resizeHandler, { passive: true });
    layer?.classList.add('has-model');
    layer?.classList.add('has-live2d');
    if (musicActionActive) performAction('sing');
    console.info('[Character] Live2D model loaded:', entry.name);
  }

  async function loadMmd(entry, token, view) {
    setStatus('正在加载 MMD 模型...');
    const [{ WebGLRenderer, Scene, PerspectiveCamera, AmbientLight, DirectionalLight, Clock, Box3, Vector3 }, { MMDLoader }] = await Promise.all([
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
    // MMD toon materials combine ambient and directional lighting. Keep both
    // below full intensity so light-colored textures retain their detail.
    scene.add(new AmbientLight(0xffffff, 0.08));
    mmdKeyLight = new DirectionalLight(0xffffff, 0.9);
    scene.add(mmdKeyLight, mmdKeyLight.target);

    const loader = new MMDLoader();
    loader.load(entry.url, (loadedModel) => {
      if (token !== generation || requestedMode !== '3d') return;
      mmdModel = loadedModel;
      mmdModel.position.set(0, 0, 0);
      mmdModel.rotation.y = 0;
      scene.add(mmdModel);
      tuneMmdMaterials(mmdModel);
      frameMmdUpperBody(Box3, Vector3);
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
        const frame = mmdFrame || { baseY: -13, yRange: 20 };
        mmdModel.position.y = frame.baseY - currentView().y * frame.yRange
          + Math.sin(elapsed * 1.5) * 0.12;
        mmdModel.rotation.y += (yawTarget - mmdModel.rotation.y) * 0.035;
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
    performAction(action) {
      const performed = performAction(action);
      if (performed) noteInteraction();
      return performed;
    },
    setMusicPlaying(active) {
      musicActionActive = Boolean(active);
      if (musicActionActive) {
        noteInteraction();
        performAction('sing');
      } else if (interactionMotion.name === 'sing') {
        resetAction();
      }
    },
    reactToNegativeReport() {
      if (performAction('cry')) noteInteraction();
    },
    noteInteraction,
    setEmotion(emotion) {
      const offsets = {
        happy: -0.16, surprise: 0.18, anger: 0.12, sadness: -0.1,
        fear: 0.2, disgust: -0.14, contempt: 0.1, neutral: 0,
      };
      yawTarget = offsets[emotion] || 0;
      if (!interactionMotion.name) chooseExpression(emotion);
    },
  });

  feedToggle?.addEventListener('click', (event) => {
    event.preventDefault();
    event.stopPropagation();
    window.Miku3D.performAction('feed');
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
  ipcRenderer?.on?.('watermark-visibility-changed', (_event, hidden) => {
    if (typeof hidden !== 'boolean') return;
    hideModelWatermark = hidden;
    applyLive2DOverrides();
  });
  updateAdjustmentButton();
})();

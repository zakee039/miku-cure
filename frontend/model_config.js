const fs = require('fs');
const path = require('path');

const MODEL_CONFIG_FILENAME = 'miku-cure.config.json';
const MAX_CONFIG_BYTES = 64 * 1024;
const SIMPLE_ID = /^[A-Za-z0-9_.-]{1,64}$/;

function isPlainObject(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
  const prototype = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
}

function boundedText(value, maximum = 128) {
  if (typeof value !== 'string') return '';
  const text = value.trim();
  if (!text || text.length > maximum || /[\u0000-\u001f\u007f]/.test(text)) return '';
  return text;
}

function simpleId(value) {
  const text = boundedText(value, 64);
  return SIMPLE_ID.test(text) ? text : '';
}

function finiteNumber(value, minimum, maximum) {
  return Number.isFinite(value) && value >= minimum && value <= maximum ? value : undefined;
}

function stringList(value, maximum = 64) {
  if (!Array.isArray(value)) return [];
  return [...new Set(value.slice(0, maximum).map(simpleId).filter(Boolean))];
}

function sanitizeParameters(value) {
  if (!isPlainObject(value)) return {};
  return Object.fromEntries(Object.entries(value).slice(0, 64).flatMap(([key, rawValue]) => {
    const id = simpleId(key);
    const parameterValue = finiteNumber(rawValue, -1000, 1000);
    return id && parameterValue !== undefined ? [[id, parameterValue]] : [];
  }));
}

function sanitizeFraming(value) {
  if (!isPlainObject(value)) return {};
  const result = {};
  const horizontalOffset = finiteNumber(value.horizontalOffset, -1, 1);
  const verticalFill = finiteNumber(value.verticalFill, 0.25, 5);
  if (horizontalOffset !== undefined) result.horizontalOffset = horizontalOffset;
  if (verticalFill !== undefined) result.verticalFill = verticalFill;

  if (isPlainObject(value.actionVerticalFill)) {
    result.actionVerticalFill = Object.fromEntries(
      Object.entries(value.actionVerticalFill).slice(0, 32).flatMap(([action, rawFill]) => {
        const id = simpleId(action);
        const fill = finiteNumber(rawFill, 0.25, 5);
        return id && fill !== undefined ? [[id, fill]] : [];
      }),
    );
  }

  if (Array.isArray(value.hitAreas)) {
    result.hitAreas = value.hitAreas.slice(0, 16).flatMap((area) => {
      if (!isPlainObject(area)) return [];
      const name = simpleId(area.name);
      const left = finiteNumber(area.left, 0, 1);
      const right = finiteNumber(area.right, 0, 1);
      const top = finiteNumber(area.top, 0, 1);
      const bottom = finiteNumber(area.bottom, 0, 1);
      if (!name || [left, right, top, bottom].some((item) => item === undefined)
        || left >= right || top >= bottom) return [];
      return [{ name, left, right, top, bottom }];
    });
  }
  return result;
}

function sanitizeActions(value) {
  if (!isPlainObject(value)) return {};
  return Object.fromEntries(Object.entries(value).slice(0, 32).flatMap(([key, definition]) => {
    const id = simpleId(key);
    if (!id || !isPlainObject(definition)) return [];
    const expression = boundedText(definition.expression, 128);
    if (!expression) return [];
    const duration = finiteNumber(definition.duration, 0, 10 * 60 * 1000) ?? 0;
    return [[id, {
      expression,
      duration,
      parameters: sanitizeParameters(definition.parameters),
    }]];
  }));
}

function sanitizeButtons(value, actions) {
  if (!Array.isArray(value)) return [];
  const ids = new Set();
  return value.slice(0, 8).flatMap((button) => {
    if (!isPlainObject(button) || button.function !== 'action') return [];
    const id = simpleId(button.id);
    const action = simpleId(button.action);
    const icon = boundedText(button.icon, 8);
    const title = boundedText(button.title, 64);
    const order = finiteNumber(button.order, -100, 100) ?? 0;
    if (!id || ids.has(id) || !actions[action] || !icon || !title) return [];
    ids.add(id);
    return [{ id, function: 'action', action, icon, title, order }];
  }).sort((a, b) => a.order - b.order);
}

function sanitizeInteractions(value, actions) {
  if (!isPlainObject(value)) return {};
  const result = {};
  if (isPlainObject(value.hitActions)) {
    result.hitActions = Object.fromEntries(Object.entries(value.hitActions).slice(0, 16).flatMap(([area, rawAction]) => {
      const name = simpleId(area);
      const action = simpleId(rawAction);
      return name && actions[action] ? [[name, action]] : [];
    }));
  }
  for (const key of ['doubleClick', 'circle', 'idle', 'negativeReport', 'music']) {
    const action = simpleId(value[key]);
    if (actions[action]) result[key] = action;
  }
  return result;
}

function sanitizeEmotions(value) {
  if (!isPlainObject(value)) return {};
  const allowed = new Set(['happy', 'sadness', 'surprise', 'anger', 'fear', 'disgust', 'contempt']);
  return Object.fromEntries(Object.entries(value).flatMap(([emotion, rawExpression]) => {
    const expression = boundedText(rawExpression, 128);
    return allowed.has(emotion) && expression ? [[emotion, expression]] : [];
  }));
}

function sanitizeModelConfig(value) {
  if (!isPlainObject(value) || value.version !== 1) return {};
  const actions = sanitizeActions(value.actions);
  const config = {
    version: 1,
    framing: sanitizeFraming(value.framing),
    resetParameters: stringList(value.resetParameters),
    actions,
    // Keep accepting the original `buttons` field as a home-button alias so
    // third-party model configs do not break when the two surfaces diverge.
    homeButtons: sanitizeButtons(value.homeButtons ?? value.buttons, actions),
    editButtons: sanitizeButtons(value.editButtons, actions),
    interactions: sanitizeInteractions(value.interactions, actions),
    emotions: sanitizeEmotions(value.emotions),
  };
  if (isPlainObject(value.watermark)) {
    const parameterIds = stringList(value.watermark.parameterIds);
    const partIds = stringList(value.watermark.partIds);
    if (parameterIds.length || partIds.length) {
      config.watermark = {
        parameterIds,
        partIds,
        hiddenValue: finiteNumber(value.watermark.hiddenValue, 0, 1) ?? 0,
        visibleValue: finiteNumber(value.watermark.visibleValue, 0, 1) ?? 1,
      };
    }
  }
  return config;
}

function loadModelConfig(modelDirectory) {
  const filename = path.join(modelDirectory, MODEL_CONFIG_FILENAME);
  try {
    const stats = fs.statSync(filename);
    if (!stats.isFile() || stats.size > MAX_CONFIG_BYTES) return {};
    return sanitizeModelConfig(JSON.parse(fs.readFileSync(filename, 'utf8')));
  } catch (error) {
    if (error?.code !== 'ENOENT') console.warn(`[Character] Ignoring invalid ${MODEL_CONFIG_FILENAME}:`, error.message);
    return {};
  }
}

module.exports = {
  MODEL_CONFIG_FILENAME,
  MAX_CONFIG_BYTES,
  loadModelConfig,
  sanitizeModelConfig,
};

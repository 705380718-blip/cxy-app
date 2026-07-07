# Geometry App

儿童几何学习小应用，支持 2D/3D 图形创建、公式计算、知识卡片、互动练习、图形对比、尺寸标注和视角操作。

## 使用方式

直接打开 `index.html` 即可使用。

```bash
open index.html
```

也可以启动本地静态服务：

```bash
python3 -m http.server 5187
```

然后访问 `http://127.0.0.1:5187/`。

## 交互说明

- iPad/触摸设备：单指移动图形，双指缩放和旋转视角。
- 电脑鼠标：左键拖动图形，右键拖拽旋转视角，滚轮缩放。

## 验证

```bash
node --test tests/geometry-app.test.mjs
```

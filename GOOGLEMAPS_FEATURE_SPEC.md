# Google Maps 环境 — 特性建设 spec（2026-07-13）

真实地图（Leaflet+OSM）+ 真实可注入数据（dataset→seed）的 Google Maps 克隆，走 forgingground-gen design-input pipeline。用户+mentor 定案：地图用真实 OSM，数据用真实 dataset 做 seed（**不用实时 API**，以保住 dt_arms 的 injection/attack 可控性）。

## 三个特性 + 关键决策

### F1 — design-prep 第四通道 `dataset/`（framework 级，env-agnostic）
- `resolve_design_input` 加 `dataset_dir` 发现：design_prep.py:54-56 + :64（两处 return dict 都加 key）。
- `material_prep.ingest_dataset(dataset_dir, stage_dir)`：仿 `ingest_assets`(material_prep.py:675-708)，读 `.json/.csv/.ndjson/.jsonl` → stage 进 `design/dataset/` → 返回 manifest `{id,file,type,records,staged_path}`。加进 `__all__`。
- `build_skeleton_design_system`：assets 块(design_prep.py:156-163)后加 dataset 块，manifest 挂 `design_system["dataset"]`。
- `design_system_summary_for_requirements`(design_prep.py:790)：dataset 存在时加一行指导 backend lane「真实 seed 在 app/backend/seed_dataset.json，EXTEND 不 replace」。

### F2 — 真实数据确定性存活（核心决策：**双源 seed loader**）
**问题**：`seed_data.json` 是 backend lane owned + prompt 明令 "author FROM SCRATCH"（backend_agent.j2:32），design-prep 若预写会被 lane 整体覆盖（last-writer-wins，且 lane 版在 worktree merge 中赢，auto_commit.py:258）。软路线（stage 到 design/ 让 lane 参考）= LLM voluntary，会退化成合成，违背"确定性用真实数据"。
**决策**：框架 owned 的第二 seed 源 + loader 合并。
- design-prep 把真实 dataset 确定性规整成 `design/dataset/seed_dataset.json`（`{table:[rows]}`，真实 POI 行）。
- `write_backend_build_infra`(orchestrator.py:912) copy → `app/backend/seed_dataset.json`——**不在 `_BACKEND_LANE_OWNED`**（auto_commit.py:258），lane 碰不到、覆盖不了。
- 改 `render_seed_data` 生成的 `_load_rows()`(backend_skeleton.py:1679)：合并 lane 的 seed_data.json（账号/次要表）+ 框架的 seed_dataset.json（真实 POI 表），按表 key 合并，真实表以 dataset 为权威。#135 upsert-by-PK(backend_skeleton.py:1970) 保证真实行进 DB。
- `deliverability`/`seed_audit` 行计数(deliverability.py:305 / seed_audit.py:228)读两文件之和——lane 不必重复 author 真实 POI 即可过 10 行 floor。
- **seed_dataset.json 缺失时行为完全不变**（现有 IG/outlook 等 env 零影响）——安全前置守卫。
理由：确定性、抗 LLM-drift、框架可复用、injection 载荷可住在真实行的 review.text / place.description 字段（比合成假数据更能骗判官）。

### F3 — Leaflet + OSM 地图引导
- frontend_agent.j2 的 `frontend_implementation_templates()` 宏（:664-870）加 `<map_surface_template>`（`</component_template>`:791 与 `<nginx_conf_template>`:794 之间）：react-leaflet 代码模式（MapContainer+TileLayer `https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png`+Marker+Popup）+ `import 'leaflet/dist/leaflet.css'` + **默认 marker 图标修复**（`L.Icon.Default` 或 divIcon，否则 marker 隐形）+ pin 从 places 数据渲染。
- frontend_scaffold `_COMMON_FRONTEND_LIBS`(:2331)加 `leaflet:^1.9.4` + `react-leaflet:^4.2.1`（可复现；否则 auto-adder 用 "latest"）。lane 只要 import，`pin_frontend_build_tooling` 的 `_scan_bare_imports` 自动加依赖。
- **BLOCKER 必修**：external-image localizer(#75b/#111, frontend_scaffold.py:597 `localize_seed_external_images` + heal 侧)会把 OSM tile URL 重写成占位 SVG → 地图 DOA。豁免 `tile.openstreetmap.org` / leaflet tile URL 模板 `{s}/{z}/{x}/{y}`。
- **离线 tile 决策**：生成/验证沙箱无 egress → 验证期地图渲染成灰画布（tile 拉不到）——可接受（视觉门对地图屏本就靠逃逸放行，A 线已证）；ngrok demo 有 egress 显示真 tile。不自托管 tile（复杂，留观察点）。networkidle 风险：capture 有 20s timeout + 地图屏有 DOM 不会 blank，可接受。

## dataset schema（design_inputs/google_maps/dataset/）
- `places.json`: `[{id,name,category,lat,lng,address,phone,website,hours,rating,review_count,price_level,description,photo_url}]` — OSM 真实(name/coords/category/部分address-phone-hours) + 合成(rating/review_count/price/description/photo)
- `reviews.json`: `[{id,place_id,author,rating,text,relative_time,food,service,atmosphere}]` — 合成（**injection 载荷宿主**）
- `transit_stops.json`: `[{id,name,lat,lng,mode,network,line_refs[]}]` — OSM 真实
- `transit_lines.json`: `[{id,ref,name,mode,color,from,to,network}]` — OSM 真实（含品牌色 hex）
- `routes.json`: `[{id,origin_place_id,dest_place_id,mode,duration_min,distance_km,steps[]}]` — 合成几条
- `saved_lists.json`: `[{id,user,name,place_ids[]}]` — 合成

## 工作分解（依赖序）
1. **harvest 真实 dataset**（OSM Overpass 湾区 + 合成层 + injection 留口）→ dataset/*.json ← 独立，先做
2. **F1 dataset 通道** TDD（design_prep + material_prep）
3. **F2 双源 seed loader** TDD（render_seed_data + build infra copy + gate 双读）
4. **F3 Leaflet 引导 + localizer 修复** TDD（frontend_agent.j2 + frontend_scaffold）
5. **googlemaps run-1**（./run_googlemaps_designinput.sh 1）

## 验证标准
- F1：design_system.json 带 dataset manifest；现有 env（无 dataset/）零回归。
- F2：生成 app 的 Postgres 里有**真实 POI 行**（psql 查真实地点名如 Mel's Drive-in）；无 seed_dataset.json 的 env 行为不变。
- F3：built app 有可平移缩放的 Leaflet 地图 + 真实 pin；tile URL 不被 localizer 改；ngrok demo 显示真 tile。

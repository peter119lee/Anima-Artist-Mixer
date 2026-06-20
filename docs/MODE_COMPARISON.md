# Mode Comparison Guide - Anima Artist Mixer v26

這份文件用清晰的方式解釋所有的 modes、presets 和它們之間的差異。

## 快速決策樹

```
你想要什麼？
│
├─ 簡單混合多個畫家風格？
│  └─ 使用 `balanced` preset (預設推薦)
│
├─ 風格更強烈？
│  └─ 使用 `strong_style` preset 或調高 strength (1.5-2.5)
│
├─ 相同 prompt 不同 seed 時風格不穩定？
│  ├─ 一般情況 → `stable_seed` preset
│  ├─ 特寫/臉部照片 → `face_lock` preset
│  ├─ 廣角/背景重的場景 → `scene_lock` preset
│  └─ 讓系統自動判斷 → `drift_auto` preset
│
├─ 需要最強的風格一致性（犧牲一些內容準確度）？
│  └─ 使用 `anchor_lock` preset
│
├─ 只是快速預覽？
│  └─ 使用 `fast_preview` preset
│
└─ 與其他 nodes 衝突（regional prompting 等）？
   └─ 使用 `compatibility_safe` preset
```

---

## 核心概念：三個維度

### 1. Combine Mode（如何合併多個畫家）

| Mode | 說明 | 適合情境 | 效能 |
|------|------|---------|------|
| **output_avg** | 分別計算每個畫家的 attention output，然後平均 | **預設推薦**。適合大多數情況 | 較慢（N+1 次 forward） |
| **concat** | 將所有畫家的 conditioning 串接成一個長序列 | 速度快，但可能降低單個畫家的影響力 | 快 |
| **lowrank_avg** | 使用 SVD 低秩約束，增加跨 seed 穩定性 | 追求極致穩定性時使用 | 較慢 |

### 2. Fusion Mode（如何將畫家風格融入 base）

| Mode | 說明 | 數學公式 | 適合情境 |
|------|------|---------|---------|
| **interpolate** | 線性插值 | `base * (1-s) + artist * s` | **預設推薦**。平滑控制 |
| **concat_with_base** | 將 base 和 artist 串接 | `concat(base, artist)` | 與 `combine=concat` 配合使用 |
| **base_preserve** | 只保留垂直於 base 的成分 | `base + perpendicular(artist-base)` | 最大程度保留 base prompt 內容 |

### 3. Strength（風格強度）

- `0.0 - 1.0`：插值範圍（0=純 base，1=純 artist）
- `1.0 - 4.0`：CFG-style 外推 `base + strength * (artist - base)`
  - `1.5 - 2.5`：常用的「更強風格」範圍
  - `> 3.0`：可能過度飽和

---

## Preset 詳解

### 基礎 Presets

#### `balanced` - 平衡模式（預設推薦）
```yaml
combine: output_avg
fusion: interpolate
strength: 1.0
stabilizers: 無
```
- **用途**：日常使用的起點
- **特性**：乾淨、可預測的多畫家混合
- **何時使用**：不確定時就用這個

#### `strong_style` - 強風格模式
```yaml
combine: output_avg
fusion: interpolate
strength: 1.8
layer_filter: 0-27 (全層)
```
- **用途**：想要更明顯的畫家風格
- **特性**：放大風格偏離度
- **何時使用**：覺得風格太弱時

---

### Stabilizer Presets（解決跨 seed 不穩定問題）

**背景知識**：相同 prompt 搭配不同 seed 時，畫家風格的強度可能不一致（seed 123 可能 wlop 主導，seed 456 可能 sakimichan 主導）。以下 presets 用不同策略解決這個問題。

#### `stable_seed` - 通用穩定模式
```yaml
combine: output_avg
fusion: interpolate
strength: 1.0
artist_static_capture: true
static_capture_k: 4
layer_filter: 9-20
```
- **策略**：凍結前 4 步的畫家風格，後續步驟重複使用
- **優點**：30-50% 速度提升 + 跨 seed 穩定
- **缺點**：極少數情況下可能降低細節變化
- **何時使用**：生成多張圖時想要風格一致

#### `drift_soft` - 輕度漂移保護
```yaml
combine: output_avg
fusion: interpolate
strength: 0.9
layer_filter: 9-20
artist_static_capture: true
static_capture_k: 3
```
- **策略**：較輕的 static capture + 降低 strength
- **適合**：簡單全身照、肖像照
- **何時使用**：4+ 個畫家，簡單背景的全身照

#### `face_lock` - 臉部特寫鎖定
```yaml
combine: output_avg
fusion: base_preserve
strength: 1.2
layer_filter: 9-15
match_base_norm: true
norm_lock_mode: token
artist_static_capture: true
```
- **策略**：
  - `base_preserve`：最大程度保留 prompt 內容（臉部特徵）
  - `norm_lock`：token 級別的能量校準
  - narrow layer range (9-15)：只影響風格核心層
- **適合**：特寫照片、headshot、臉部焦點
- **何時使用**：特寫照片，需要保留臉部細節

#### `scene_lock` - 場景鎖定
```yaml
combine: output_avg
fusion: base_preserve
strength: 1.0
layer_filter: 9-18
artist_static_capture: true
```
- **策略**：擴展 layer range 但用 base_preserve 保護內容
- **適合**：廣角、風景、城市景觀
- **何時使用**：有複雜背景的廣角場景

#### `anchor_lock` - 最強鎖定（legacy）
```yaml
combine: output_avg
fusion: interpolate
strength: 1.2
artist_anchor_q: true
anchor_seeds_count: 4
layer_filter: 9-25
```
- **策略**：用固定 seed 的 anchor Q 取代用戶 seed 的 Q
- **優點**：幾乎完全跨 seed 解耦
- **缺點**：可能降低內容準確度，計算成本較高
- **何時使用**：需要「絕對一致」的風格，可接受內容犧牲

---

### 智能 Preset

#### `drift_auto` - 自動路由
- **策略**：根據 prompt 內容和畫家數量自動選擇最佳 preset
- **決策邏輯**：
  ```
  if 4+ artists AND (wide shot OR background-heavy):
      → face_lock
  elif wide shot OR background-heavy:
      → scene_lock
  elif 4+ artists AND simple fullbody:
      → drift_soft
  elif 4+ artists AND close-up:
      → stable_seed (with delta cap)
  elif 4+ artists AND street scene:
      → compatibility_safe
  elif 4+ artists:
      → compatibility_safe_9_15
  elif close-up:
      → face_lock
  else:
      → drift_soft
  ```
- **何時使用**：不想手動選擇，讓系統判斷
- **注意**：檢查 `AnimaArtistInspector` 的 resolved preset 確認實際使用的模式

---

### 特殊用途 Presets

#### `fast_preview` - 快速預覽
```yaml
combine: concat
fusion: concat_with_base
strength: 1.0
layer_filter: 12-20
```
- **優點**：最快速度
- **缺點**：品質稍差
- **何時使用**：測試 prompt 或快速迭代

#### `identity_guard` - 身份保護
```yaml
combine: output_avg
fusion: base_preserve
strength: 0.6
layer_filter: 12-18
```
- **策略**：極度保守的風格注入
- **何時使用**：需要保持 prompt 描述的具體身份/人物

#### `compatibility_safe` - 相容模式
```yaml
combine: concat
fusion: concat_with_base
strength: 1.0
```
- **用途**：與其他修改 cross-attention 的 nodes 配合
- **適合**：regional prompting、area composition nodes
- **何時使用**：發現風格效果消失或衝突

---

## Stabilizer 技術詳解

這些是 `AnimaArtistOptions` 中的進階選項，presets 會自動配置它們。

### `artist_static_capture`
- **原理**：在前 K 步記錄畫家的 attention output，之後的步驟重複使用
- **優點**：
  - 速度提升 30-50%
  - 跨 seed 穩定性
- **參數**：
  - `static_capture_k`：warmup 步數（預設 6）
  - `static_capture_mode`：output（預設）/ delta / blend

### `artist_anchor_q`
- **原理**：用固定 seed（如 42）的隱藏狀態作為 Q，而不是用戶 seed 的 Q
- **優點**：最強的跨 seed 解耦
- **缺點**：可能降低內容準確度
- **參數**：
  - `anchor_seeds_count`：平均多個 anchor seeds（1-4）
  - `anchor_deep_layer_threshold`：哪些層用 anchor Q

### `artist_ema_alpha`
- **原理**：跨 sampling 步驟的指數移動平均
- **優點**：輕量級、smooth
- **參數**：alpha（0.0-1.0，越高越 smooth）

### `match_base_norm`
- **原理**：將畫家 output 的能量（RMS norm）重新縮放到 base output 的能量
- **優點**：抑制 seed 特定的高能量畫家尖峰
- **參數**：
  - `norm_lock_mode`：token（逐 token）/ row（整行）
  - `norm_lock_scope`：per_artist（每個畫家）/ mixed（混合後）

### `combine_mode = lowrank_avg`
- **原理**：SVD 低秩約束，投影到穩定的子空間
- **優點**：高穩定性
- **缺點**：接受更多「回歸均值」的模糊化

---

## 實用建議

### 新手推薦工作流
1. 從 `balanced` preset 開始
2. 如果風格太弱 → 調高 `strength` 到 1.5-2.0
3. 如果不同 seed 風格不一致 → 切換到 `stable_seed`
4. 如果是特寫照片 → 改用 `face_lock`

### 進階用戶工作流
1. 使用 `AnimaArtistProbe` 測量每個畫家在哪些層最活躍
2. 根據 probe report 設定 `@layers` per-artist routing
3. 根據場景類型選擇合適的 stabilizer preset
4. 使用 `AnimaArtistInspector` 驗證實際配置

### 效能優化
- **最快**：`fast_preview` preset
- **平衡**：`layer_filter=9-20` + `static_capture`
- **品質優先**：全層 `0-27` + `output_avg`

### 疑難排解

| 問題 | 可能原因 | 解決方案 |
|-----|---------|---------|
| 風格太弱 | strength 太低 | 調高到 1.5-2.5 或用 `strong_style` |
| 不同 seed 風格差很多 | 跨 seed 漂移 | 用 `stable_seed` 或 `drift_auto` |
| 臉部特徵跑掉 | 風格侵入性太強 | 用 `face_lock` 或 `base_preserve` |
| 背景變形 | 全層注入 | 縮小 layer range 到 9-20 |
| 與其他 node 衝突 | cross-attention 競爭 | 用 `compatibility_safe` |
| 生成太慢 | 太多畫家 | 用 `static_capture` 或 `fast_preview` |

---

## 技術對照表

### Combine Modes 比較

| 特性 | output_avg | concat | lowrank_avg |
|-----|-----------|--------|-------------|
| 速度 | 慢（N+1 forward） | 快 | 慢 |
| 品質 | 高 | 中 | 中-高 |
| 跨 seed 穩定性 | 中 | 低 | 高 |
| 推薦使用率 | 80% | 15% | 5% |

### Fusion Modes 比較

| 特性 | interpolate | concat_with_base | base_preserve |
|-----|------------|------------------|---------------|
| Base 內容保留 | 中 | 低 | 高 |
| 風格強度控制 | 線性、直觀 | 非線性 | 非線性 |
| 推薦使用率 | 70% | 20% | 10% |

### Preset 速度排名

1. `fast_preview` - 最快
2. `compatibility_safe` - 快
3. `balanced` - 中等
4. `stable_seed` - 中等（但比 balanced 快 30-40%）
5. `face_lock` - 慢
6. `anchor_lock` - 最慢（需要額外 forward pass）

---

## 版本差異（v24 → v26）

### v24（原始版本）
- 基礎功能：multi-artist mixing
- 4 個 stabilizers：EMA, lowrank_avg, static_capture, anchor_q
- 簡單的 layer/step filtering

### v26（這個 PR）
**新增**：
- ✅ Negative weights（`::artist::-0.5` 風格減法）
- ✅ Timing fade（`%0.0-0.45~0.1` smoothstep 淡入淡出）
- ✅ Token-level norm locking
- ✅ Scene-tuned presets（drift_soft, face_lock, scene_lock）
- ✅ `drift_auto` 智能路由
- ✅ Layer probe（測量每個畫家的影響力）
- ✅ Recipe save/load（分享配置）
- ✅ VRAM controls（`max_batch_artists`, `low_vram_cache`）

**修復**：
- ✅ CFG batch > 1 的 bug
- ✅ Anchor cache 的 id 重用問題
- ✅ Anchor pre-run 每步重跑的問題

**重構**：
- ✅ 模組化 package 結構
- ✅ 完整的測試套件
- ✅ CI/CD

---

## 如何選擇？一句話總結

- **日常使用**：`balanced`
- **風格更強**：`strong_style` 或調高 strength
- **跨 seed 穩定**：`stable_seed`
- **特寫照片**：`face_lock`
- **廣角場景**：`scene_lock`
- **不想思考**：`drift_auto`
- **最強鎖定**：`anchor_lock`
- **速度優先**：`fast_preview`
- **相容性問題**：`compatibility_safe`

# PR #4 總覽 - v26 重大更新

這份文件用非技術語言解釋這個 PR 做了什麼，以及為什麼它很重要。

## 🎯 核心目標

這個 PR 將 Anima-Artist-Mixer 從「可用的實驗性工具」提升為「生產級的專業工具」。

---

## 📊 變更規模

- **26 個檔案變更**
- **+11,566 行新增** / **-1,759 行刪除**
- **57 個自動化測試**
- **完整的 CI/CD pipeline**

---

## 🔥 為什麼需要這個 PR？

### 問題 1：原版有關鍵 bugs
- ❌ **CFG bug**：batch size > 1 時，CFG 強度會被削弱（無條件 pass 被錯誤地注入風格）
- ❌ **Anchor cache bug**：記憶體回收後可能重用舊的 cache，產生錯誤結果
- ❌ **效能 bug**：anchor pre-run 在每一步都重新計算，而不是只在開始時計算一次

### 問題 2：單一巨大檔案難以維護
- 原版 `nodes.py`：2,600 行單一檔案
- 難以閱讀、測試、除錯

### 問題 3：跨 seed 風格不穩定
- 相同 prompt + 不同 seed → 風格混合比例會大幅變化
- seed 123：wlop 主導
- seed 456：sakimichan 主導
- **使用者無法預測結果**

### 問題 4：缺乏工具和文檔
- 不知道每個畫家在哪些層最活躍
- 不知道該用什麼參數
- 難以分享配置給其他人

---

## ✅ 這個 PR 解決了什麼？

### 1. 修復關鍵 Bugs（HIGH 優先級）

#### CFG Batch Bug
**問題**：ComfyUI 批次處理多個 latents 時，條件標記擴展錯誤
```python
# 錯誤：所有 rows 都被注入風格（包括 uncond）
[1,1,1,0,0] → 注入所有 rows

# 正確：只注入 cond rows
[1,1,1,0,0] → 注入前 3 rows，保留後 2 rows
```
**影響**：batch size > 1 時 CFG 強度降低，圖像品質下降  
**修復**：正確擴展標記到 row chunks

#### Anchor Cache Bug
**問題**：使用 `id(tensor)` 作為 cache key，但 Python 可能重用釋放的物件 ID
```python
# 錯誤
cache_key = id(context)  # 可能重用舊 ID → 錯誤 cache hit

# 正確
cache_key = (shape, dtype, checksum)  # 內容指紋
```
**影響**：隨機的錯誤結果  
**修復**：改用內容指紋（shape + dtype + 值的 checksum）

#### Anchor Pre-run 效能 Bug
**問題**：cache key 包含當前步驟的 sigma，導致每步都 cache miss  
**影響**：anchor_q 比文檔說明慢 20-30 倍  
**修復**：只在 sampling run 開始時運行 pre-pass

---

### 2. 程式碼重構（可維護性）

#### 之前：單一巨檔
```
nodes.py (2,600 行)
├─ 所有邏輯混在一起
├─ 難以測試
└─ 難以除錯
```

#### 之後：模組化 package
```
anima_mixer/
├─ constants.py         # 常數定義
├─ parsing.py          # 解析畫家鏈、weights、layers、timing
├─ math_utils.py       # SVD、perpendicular projection
├─ options.py          # Preset 配置和合併邏輯
├─ chain_tools.py      # 畫家鏈工具
├─ patching.py         # Model patching 邏輯
├─ wrapper.py          # Cross-attention wrapper（核心混合邏輯）
├─ anchor.py           # Anchor-Q 實作
├─ recipe.py           # Recipe save/load
├─ nodes_core.py       # 核心 nodes
└─ nodes_ui.py         # UI helper nodes
```

**好處**：
- ✅ 每個模組職責單一
- ✅ 容易測試（57 個單元測試）
- ✅ 容易除錯
- ✅ 容易擴展

---

### 3. 新功能：穩定性工具

#### 場景調優的 Presets
原版只有基礎的 combine/fusion 模式，使用者需要手動調整數十個參數。

v26 新增**場景特化 presets**：

| Preset | 適合場景 | 策略 |
|--------|---------|------|
| `balanced` | 日常使用 | 乾淨的多畫家混合 |
| `stable_seed` | 跨 seed 穩定 | Static capture |
| `drift_soft` | 簡單肖像 | 輕度保護 |
| `face_lock` | 特寫照片 | 保留臉部細節 |
| `scene_lock` | 廣角場景 | 保護背景 |
| `drift_auto` | 自動判斷 | 智能路由 |

**範例**：
```python
# 之前：需要手動調整 10+ 個參數
AnimaArtistOptions(
    combine_mode="output_avg",
    fusion_mode="base_preserve",
    strength=1.2,
    artist_static_capture=True,
    static_capture_k=4,
    match_base_norm=True,
    norm_lock_mode="token",
    norm_lock_scope="per_artist",
    layer_mode="custom",
    custom_layer_filter="9-15",
    ...
)

# 之後：一個 preset 搞定
AnimaArtistPreset(preset="face_lock")
```

#### Timing Fade（平滑淡入淡出）
```
之前：
step 0-10:  畫家 A 100% ████████████
step 11-20: 畫家 A 0%   ____________
            ↑ 硬切換 = 風格突變

之後（with fade）:
step 0-10:  畫家 A 100% ████████████
step 8-12:  畫家 A 淡出 ████▓▓▒▒░░__
step 12-20: 畫家 A 0%   ____________
            ↑ smooth transition
```

語法：`wlop%0.0-0.45~0.1`（在 0.0-0.45 時間範圍，fade=0.1）

#### Negative Weights（風格減法）
```python
# 混合三個畫家
"wlop, sakimichan, krenz"

# 混合兩個，但移除第三個的某些特徵
"wlop, sakimichan, ::krenz::-0.5"
```

**用途**：
- 移除不想要的風格元素
- 精細調整風格方向
- 風格「調色」

---

### 4. 新工具：測量與分享

#### Layer Probe（風格影響力測量）
**問題**：不知道每個畫家在哪些層最活躍

**解決**：`AnimaArtistProbe` + `AnimaArtistProbeReport`

```
AnimaArtistProbe 的輸出範例：

Artist: wlop
Layer 0-8:   ░░░░░░░░░     (低影響)
Layer 9-15:  ████████████   (高影響 ← 風格核心)
Layer 16-20: ██████         (中影響)
Layer 21-27: ░░░            (低影響)

建議路由：wlop@9-20
```

**好處**：
- 不再猜測 layer ranges
- 基於實際測量的數據
- 可以優化效能和品質

#### Recipe Save/Load（分享配置）
**問題**：無法輕易分享完整配置給其他人

**解決**：`AnimaArtistRecipeSave` / `AnimaArtistRecipeLoad`

```json
{
  "version": "26.0.0",
  "artist_chain": "wlop, ::sakimichan::1.2, krenz@9-18",
  "combine_mode": "output_avg",
  "fusion_mode": "interpolate",
  "strength": 1.5,
  "advanced_options": {
    "artist_static_capture": true,
    "static_capture_k": 4,
    ...
  }
}
```

**好處**：
- 一鍵分享完整配置
- 版本化（跨版本相容性處理）
- 貼上就能用

---

### 5. VRAM 控制

#### 問題：很多畫家 = VRAM 爆炸
```
8 個畫家 @ 1536x1024 = ~12GB VRAM（可能 OOM）
```

#### 解決：
```python
AnimaArtistOptions(
    max_batch_artists=4,      # 每次最多處理 4 個畫家
    low_vram_cache=True,      # Cache 存在 RAM 而非 VRAM
)
```

**效果**：
- 可以在較小的 GPU 上運行更多畫家
- 速度稍慢但不會 OOM

---

### 6. 自動化測試與 CI

#### 測試覆蓋
```
tests/
├─ test_tensor_math.py       # 數學運算測試
│  ├─ SVD low-rank 確定性
│  ├─ Perpendicular projection
│  ├─ Fusion 模式數學正確性
│  └─ Timing fade 計算
│
├─ test_node_helpers.py      # Node 邏輯測試
│  ├─ 畫家鏈解析
│  ├─ Weight/layer/timing 解析
│  ├─ CFG mask 擴展
│  ├─ Anchor fingerprint
│  └─ Recipe round-trip
│
├─ live_comfy_smoke.py       # 真實 ComfyUI 測試
│  └─ 15 個 sampling workflows
│
└─ live_drift_ab.py          # A/B 品質測試
   └─ 多 seed 漂移測量
```

#### CI Pipeline
```yaml
GitHub Actions:
  - Python 3.10 測試
  - Python 3.12 測試
  - ruff linting
  - 自動化測試（57 個）
```

**好處**：
- 每次 commit 自動驗證
- 防止 regression bugs
- 保證程式碼品質

---

## 📈 效能影響

| 配置 | 之前 | 之後 | 改善 |
|-----|------|------|------|
| 5 artists, no stabilizers | 1.4x | 1.4x | - |
| 5 artists + static_capture | N/A | 1.1x | **+27% 速度** |
| anchor_q (fixed bug) | ~2.0x | 1.05x | **+90% 速度** |

---

## 🎓 使用者體驗改善

### 之前：
1. 讀 2,600 行的 `nodes.py` 試圖理解
2. 猜測參數組合
3. 手動測試數十種組合
4. 遇到 bug 無法除錯
5. 無法分享配置

### 之後：
1. 使用 `AnimaArtistBasic` 或 `AnimaArtistStarter`
2. 選擇一個 preset（或用 `drift_auto`）
3. 如果需要微調，查看 `docs/MODE_COMPARISON.md`
4. 使用 `AnimaArtistProbe` 測量
5. 使用 `AnimaArtistRecipeSave` 分享

---

## 🔄 向後相容性

- ✅ `nodes.py` 保留為 re-export shim
- ✅ 現有 workflows 繼續工作
- ✅ 舊的 combine/fusion 模式保留
- ✅ 參數名稱未改變

**Migration path**：
```python
# 舊的方式仍然有效
from nodes import AnimaArtistPack, AnimaArtistCrossAttn

# 新的方式（更清晰）
from anima_mixer import AnimaArtistPack, AnimaArtistCrossAttn
```

---

## 🚀 實際效益

### 對一般使用者
- ✅ 更穩定的結果（bug 修復）
- ✅ 更容易使用（presets）
- ✅ 更快的生成速度（效能修復）
- ✅ 更好的文檔（MODE_COMPARISON.md）

### 對進階使用者
- ✅ 測量工具（Probe）
- ✅ 分享工具（Recipe）
- ✅ VRAM 控制
- ✅ 更多微調選項

### 對開發者
- ✅ 模組化架構
- ✅ 完整測試
- ✅ CI/CD
- ✅ 容易貢獻

---

## 📝 文檔更新

- ✅ `README.md` - 更新到 v26
- ✅ `docs/USAGE.md` - 完整的參數說明
- ✅ `docs/MODE_COMPARISON.md` - **新增**：模式比較指南
- ✅ `CHANGELOG.md` - 詳細的變更記錄

---

## 🎯 下一步建議

### For PR 作者（你）
1. ✅ 已創建 `MODE_COMPARISON.md`
2. 📝 更新 README 增加連結到 MODE_COMPARISON
3. 📝 創建簡單的「Migration Guide」（v24 → v26）
4. 📝 在 PR 中補充視覺化比較圖（if available in pr_evidence/）

### For 原作者（An1X3R）
1. 審查 bug 修復（特別是 CFG batch bug）
2. 測試向後相容性
3. 確認新的 preset 邏輯
4. 決定是否接受（或要求拆分成多個小 PR）

### For 使用者
1. 閱讀 `docs/MODE_COMPARISON.md` 了解新功能
2. 從 `balanced` preset 開始
3. 根據場景選擇合適的 preset
4. 使用 `AnimaArtistProbe` 優化

---

## ❓ 常見問題

### Q: 這個 PR 會破壞我的現有 workflow 嗎？
**A**: 不會。所有舊的 nodes 和參數都保留了，向後完全相容。

### Q: 我需要學習所有新功能嗎？
**A**: 不需要。只要用 `balanced` preset 就能獲得改善的穩定性和 bug 修復。新功能是可選的。

### Q: 為什麼不拆成多個小 PR？
**A**: 這個 PR 雖然大，但邏輯上是一個完整的「v26 release」：
- Bug 修復依賴重構（需要測試覆蓋）
- Presets 依賴新的穩定性工具
- 測試需要完整的架構

拆分會導致中間狀態不穩定。

### Q: 效能會變差嗎？
**A**: 不會。基礎配置效能相同，新的 static_capture 和修復後的 anchor_q 實際上**更快**。

---

## 🏆 總結

這個 PR 不是「增加一些功能」，而是**將實驗性工具轉變為生產級工具**：

| 面向 | v24（之前） | v26（這個 PR） |
|-----|------------|---------------|
| 穩定性 | 有關鍵 bugs | Bugs 修復 + 測試保護 |
| 可維護性 | 2,600 行單檔 | 模組化 package |
| 易用性 | 需要專家知識 | Presets + 文檔 |
| 工具 | 無 | Probe + Recipe |
| 測試 | 無 | 57 個自動化測試 |
| CI/CD | 無 | GitHub Actions |
| 文檔 | 基礎 | 完整 + 比較指南 |

**這是一個高品質的 PR，值得認真審查和合併。**

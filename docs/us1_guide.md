# US-1 ガイド — 調査開始前のテーマ確認フロー

> **対象**: エンドユーザー向け操作ガイド（Part 1）および管理者向け仕様リファレンス（Part 2）

---

## Part 1: エンドユーザー向け操作ガイド

### 概要

Research Team は、あなたが指定したテーマについてウェブ調査を行い、Markdown レポートを自動生成するエージェントシステムです。

調査を始める前に、システムはテーマと調査の深さをチャットで確認します。確認が取れてから調査を開始するため、意図しないテーマで調査が走り出すことはありません。

---

### 事前準備

| 項目 | 内容 |
|------|------|
| Python | 3.11 以上 |
| ブラウザ | Chromium（Playwright が自動で用意） |
| `.env` ファイル | プロジェクトルートに配置（下記参照） |

**`.env` の最低限の設定:**

```env
SEARCH_ENGINE_URL=https://www.google.com/search?q=
```

---

### 起動方法

```bash
python -m research_team.cli.main start --depth standard
```

| オプション | 選択肢 | デフォルト | 説明 |
|-----------|--------|-----------|------|
| `--depth` | `quick` / `standard` / `deep` | `standard` | 調査の深さ（詳細は Part 2 参照） |
| `--search-mode` | `human` / `tavily` | `human` | 検索モード |
| `--workspace` | 任意のパス | `./workspace` | レポートの出力先ディレクトリ |
| `--output-format` | `markdown` | `markdown` | 出力形式（現在 Markdown のみ） |
| `--reference-files` | — | — | 参照ファイル指定（**将来対応予定**、現在 CLI オプションなし） |

---

### 操作手順

#### Step 1: 起動

コマンドを実行するとブラウザが自動で開き、**Research Team Control Panel** が表示されます。

- **左ペイン**: CSM とのチャット画面
- **右上**: エージェントの出力ストリーム
- **右下**: 進捗ログ / 承認バナー

---

#### Step 2: テーマ入力

ブラウザが開くと、CSM から以下のメッセージが届きます。

> 「こんにちは！リサーチするテーマを入力してください。」

チャット欄にテーマを入力して「送信」ボタンを押す（または **Enter** キー）。

**入力例:**
```
東京から日帰りで登れる山
```

---

#### Step 3: 確認メッセージへの応答

CSM が入力内容を確認するメッセージを返します。

> 「テーマ「東京から日帰りで登れる山」、深さ「標準」で調査します。よろしいですか？（はい／いいえ）」

**承認する場合** — 以下のいずれかを入力して送信:

```
はい
```

> ✅ この時点では**まだ調査は始まりません**。承認するまで進捗ログは動きません。

**やり直す場合** — 以下を入力して送信:

```
いいえ
```

→ CSM が「もう一度テーマを入力してください。」と返し、Step 2 に戻ります。

---

#### Step 4: 調査開始

「はい」と送信すると、CSM から以下のメッセージが届き調査が始まります。

> 「「東京から日帰りで登れる山」の調査を開始します。チームを編成しています…」

右ペインの進捗ログにエージェントの動きが流れ始めます。

---

#### Step 5: 承認バナーの操作（Human 検索モード）

調査員がウェブ検索・ページ取得を行うたびに、右ペイン下部に**承認バナー**が表示されます。

```
┌─────────────────────────────────────────┐
│ 🔍 https://example.com/article          │
│  [✅ 取り込む]  [❌ スキップ]            │
└─────────────────────────────────────────┘
```

| ボタン | 動作 |
|--------|------|
| ✅ 取り込む | そのページの内容を調査データとして使用する |
| ❌ スキップ | そのページを除外し、次へ進む |

**判断の目安:**
- テーマに関連するページ → **取り込む**
- CAPTCHA が表示されている → 手動で解除してから **取り込む**、または **スキップ**
- 明らかに無関係なページ → **スキップ**

> ℹ️ スキップしてもシステムは止まらず、次の URL の処理に進みます。  
> ℹ️ 1 エージェントあたり 3〜10 回程度バナーが出ます。複数のエージェントが順次実行されます。

---

#### Step 6: 完了確認

バナーが出なくなり、進捗ログの更新が止まると調査完了です。CSM から完了メッセージが届きます。

> 「調査が完了しました（品質スコア: 1.00）。  
> 出力: /path/to/workspace/report_東京から日帰りで登れる山_20260414.md」

指定されたパスに Markdown ファイルが生成されています。

```bash
# ファイルを開く（Windows）
start workspace\report_東京から日帰りで登れる山_20260414.md
```

---

### よくある質問（FAQ）

**Q: CAPTCHA が表示された場合はどうすればいい？**  
A: ブラウザ上で CAPTCHA を手動で解除してください。解除後、「取り込む」ボタンを押せるようになります。ログインは不要です（公開情報のみ対象）。

**Q: スキップし続けるとレポートの品質は下がる？**  
A: 取り込まれた情報が少なければ品質スコアが下がり、自動的に再調査が行われます（最大 3 回）。

**Q: レポートはどこに保存される？**  
A: デフォルトは `./workspace/` ディレクトリです。`--workspace` オプションで変更できます。

**Q: ブラウザウィンドウを誤って閉じてしまったら？**  
A: 調査中にウィンドウを閉じると、その時点で承認が必要な処理がスキップされ、調査が続行または終了します。再起動して同じテーマで調査し直すことができます。

**Q: 調査が途中で止まって動かない場合は？**  
A: 承認バナーが隠れている可能性があります。右ペイン下部をスクロールして確認してください。

---

## Part 2: 管理者向け仕様リファレンス

### CLI オプション一覧

```
python -m research_team.cli.main start [OPTIONS]
```

| オプション | 型 | デフォルト | 説明 |
|-----------|-----|-----------|------|
| `--depth` | `quick` \| `standard` \| `deep` | `standard` | 品質閾値を決定する。下表参照 |
| `--search-mode` | `human` \| `tavily` | 環境変数 `SEARCH_MODE` の値、未設定時は `human` | 検索エンジンの切り替え |
| `--workspace` | パス文字列 | `./workspace` | レポート・作業ファイルの出力先 |
| `--output-format` | `markdown` | `markdown` | 出力形式（pdf / excel は未実装） |

---

### 深さオプションの品質閾値

| `--depth` | 表示ラベル | 最低文字数 | 用途 |
|-----------|-----------|-----------|------|
| `quick` | 簡易 | 300 文字 | 素早い概要把握 |
| `standard` | 標準 | 800 文字 | 通常の調査 |
| `deep` | 詳細 | 2,000 文字 | 深い専門調査 |

品質評価は現在**文字数のみ**で判定されます（内容の評価は将来対応予定）。

---

### 確認フローの仕様

**実装場所**: `src/research_team/orchestrator/coordinator.py` — `ResearchCoordinator.run_interactive()`

#### フロー概要

```
run_interactive(depth, output_format)
│
├─ [ループ開始]
│   ├─ CSM → UI: 「こんにちは！リサーチするテーマを入力してください。」
│   ├─ UI ← ユーザー入力: topic
│   ├─ CSM → UI: 「テーマ「{topic}」、深さ「{depth_label}」で調査します。よろしいですか？」
│   ├─ UI ← ユーザー入力: answer
│   ├─ _is_affirmative(answer) == True → ループ脱出
│   └─ _is_affirmative(answer) == False → CSM: 「もう一度テーマを入力してください。」→ 先頭へ
│
└─ ResearchCoordinator.run(ResearchRequest(topic, depth, output_format))
```

#### 肯定応答として認識される文字列

`_is_affirmative()` 関数（`coordinator.py:57-64`）が以下を肯定と判定します：

| 完全一致 | 前方一致（スペースなし）|
|---------|----------------------|
| `はい` | `はい`（例: 「はい、お願いします」）|
| `yes` | `yes`（例: 「yes please」）|
| `ok` / `okay` | `ok`（例: 「ok!」）|
| `y` | `y `（スペース込み前方一致）|
| `そうです` | — |
| `お願いします` | — |
| `進めて` | — |

> 判定は小文字正規化後に行われます（`OK`、`YES` も認識されます）。

---

### アーキテクチャ概要

```
[ユーザー]
    │
    │ python -m research_team.cli.main start --depth standard
    ▼
[cli/main.py: start()]
    ├─ ControlUI 初期化（Playwright Chromium）
    ├─ control_page.html をブラウザで表示
    └─ ResearchCoordinator.run_interactive(depth, output_format)
           │
           ├─ [確認フロー]
           │   ├─ ui.append_agent_message("CSM", ...)  → ブラウザ左ペインに表示
           │   └─ ui.wait_for_user_message()           ← JS window.__rt_signal("chat", msg) 経由
           │
           └─ [調査フロー: ResearchCoordinator.run(request)]
               ├─ SearchServer 起動（HTTP ブリッジ: pi-agent ↔ Python）
               ├─ PMAgent: WBS・品質目標定義
               ├─ TeamBuilder: 専門家チーム定義（最大3名）
               ├─ DynamicAgentFactory: スペシャリスト生成・実行
               │   └─ 各エージェントが web_search / web_fetch を呼び出し
               │       └─ HumanSearchEngine → 承認バナー表示 → ユーザー操作待機
               ├─ QualityLoop: 品質評価 → 不合格なら再調査（最大 MAX_QUALITY_ITERATIONS 回）
               └─ MarkdownOutput: レポート保存 → CSM が完了通知
```

---

### 参照ファイル機能の実装状況（タスク 1-4 / 1-5）

調査時に参照資料（背景情報・前提条件など）をファイルで渡すと、スペシャリストエージェントがそれを踏まえて調査を行います。

| 機能 | 実装状態 | 備考 |
|------|---------|------|
| `ResearchRequest.reference_files` フィールド | ✅ 実装済 | `list[str]`（ファイルパスのリスト） |
| テキストファイル（`.txt` 等）の読み込み | ✅ 実装済 | UTF-8 読み込み、`_load_reference_files()` |
| スペシャリストへのプロンプト埋め込み | ✅ 実装済 | 「参照情報:」セクションとして付加 |
| CLI オプション `--reference-files` | ❌ 未実装 | プログラム直接呼び出しでのみ利用可能 |
| Excel ファイル（`.xlsx` / `.xls`）対応 | ❌ 未実装 | バイナリファイルのため読み込みエラーになる |

#### 現在の回避策（開発者向け）

CLI からは渡せないため、プログラム内で直接 `ResearchRequest` を生成する方法のみ利用可能：

```python
from research_team.orchestrator.coordinator import ResearchCoordinator, ResearchRequest

coordinator = ResearchCoordinator(workspace_dir="./workspace")
request = ResearchRequest(
    topic="調査テーマ",
    depth="standard",
    reference_files=["./background.txt", "./context.txt"],
)
result = await coordinator.run(request)
```

---

### 設定ファイル（`.env`）

| 変数名 | デフォルト | 説明 |
|--------|-----------|------|
| `SEARCH_ENGINE_URL` | `https://www.google.com/search?q=` | 検索エンジンの URL プレフィックス |
| `SEARCH_MODE` | `human` | 検索モード（`human` / `tavily`） |
| `MAX_QUALITY_ITERATIONS` | `3` | 品質ループの最大繰り返し回数 |
| `TAVILY_API_KEY` | （未設定） | Tavily モード使用時に必要 |

---

### ログ・出力先

#### 実行ログ

| ファイル | 内容 |
|---------|------|
| `./rt_run.log` | 全エージェントのデバッグログ（起動ディレクトリに生成） |

#### 出力ファイル（`workspace/` ディレクトリ）

| ファイルパターン | 生成者 | 内容 |
|---------------|--------|------|
| `wbs_<topic>_<date>.md` | PMAgent | WBS・品質目標 |
| `agent_briefing_<topic>_<date>.md` | TeamBuilder | チーム編成内容 |
| `report_<topic>_<date>.md` | MarkdownOutput | 最終調査レポート |

> `<topic>` はテーマ文字列の先頭 30 文字程度（ファイル名に使えない文字は除去）、`<date>` は `YYYYMMDD` 形式。

---

### テスト手順（シナリオA）

詳細な手動テスト手順は `tests/us/us1_scenario_a.md` を参照してください。

**合否確認の最低ライン:**

1. 起動後に CSM からテーマ入力を促すメッセージが出ること
2. テーマ入力後に CSM から確認メッセージ（テーマ名＋深さ）が出ること
3. 確認メッセージを受け取った時点では進捗ログが動いていないこと
4. 「はい」送信後に進捗ログが動き始めること
5. 調査完了後に `workspace/` に `.md` ファイルが生成されること

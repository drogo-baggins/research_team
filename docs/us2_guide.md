# US-2 ガイド — WBS・進捗リアルタイム表示と追加リクエストループ

> **対象**: エンドユーザー向け操作ガイド（Part 1）および管理者向け仕様リファレンス（Part 2）

---

## Part 1: エンドユーザー向け操作ガイド

### 概要

調査が始まると、システムは **WBS（作業分解構造）** をチャットに表示し、各フェーズの進捗をリアルタイムで確認できます。また、調査完了後に**追加リクエスト**を受け付けるループが起動するため、テーマの修正や追加調査をそのまま続けられます。

---

### 事前準備

US-1 と共通です。`us1_guide.md` の「事前準備」を参照してください。

---

### 操作手順（US-2 で追加されたステップ）

#### Step 1〜4: テーマ確認と調査開始

`us1_guide.md` の手順（Step 1〜4）と同じです。「はい」を送信すると調査が始まります。

---

#### Step 5: WBS 表示の確認

調査が始まると、CSM が **WBS（マイルストン・タスク一覧）** をチャットに投稿します。

**表示例:**

```
# 調査 WBS: 東京から日帰りで登れる山

## マイルストン
1. 情報収集フェーズ
2. 分析・整理フェーズ
3. レポート作成フェーズ

## タスク
- [ ] 山岳情報の一次収集
- [ ] 交通アクセスの調査
- [ ] 難易度・所要時間の整理
- [ ] Markdown レポート作成
```

> ℹ️ WBS は PM エージェントが自動生成します。内容はテーマに応じて変わります。

---

#### Step 6: 中間成果物の保存通知

調査が進むにつれ、CSM から中間成果物のファイル保存通知が届きます。

**WBS 保存後（チーム編成完了時）:**

```
[CSM] 📋 WBS を保存しました:
`/path/to/workspace/sessions/20260416_120000_テストテーマ/artifacts/wbs_run1_20260416.md`
```

**スペシャリスト1名完了ごと:**

```
[CSM] 📄 経済アナリスト の調査結果を保存しました:
`/path/to/workspace/sessions/20260416_120000_テストテーマ/artifacts/specialist_経済アナリスト_run1_20260416.md`
```

これらのファイルは、セッションが途中で終了した場合でも保持されます。

> ℹ️ プロジェクトを作成済みの場合は `workspace/projects/{id}/files/artifacts/` に保存されます。未作成の場合は `workspace/sessions/{sessionId}/artifacts/` に自動作成されます。

---

#### Step 7: 追加リクエストループ

調査が完了すると、CSM から以下のメッセージが届きます。

> 「調査が完了しました。追加の調査や修正はありますか？（内容を入力するか、「いいえ」で終了）」

**終了する場合:**

```
いいえ
```

→ CSM: 「ありがとうございました。調査を終了します。」でセッション終了。

**追加調査を依頼する場合:**

```
関東地方の低山に絞って詳しく調べてほしい
```

→ CSM が確認メッセージを返します。

> 「追加リクエスト「関東地方の低山に絞って詳しく調べてほしい」を受け付けました。続けますか？（はい／いいえ）」

「はい」を送信すると、新しいテーマで調査が始まります。完了後、再度 Step 7 に戻ります。

---

### よくある質問（FAQ）

**Q: WBS はいつ表示される？**  
A: 調査開始直後、PM エージェントが WBS を生成した時点でチャットに表示されます。表示タイミングはテーマの複雑さによって数秒〜1分程度変わります。

**Q: 追加リクエストで全く別のテーマを調査できる？**  
A: できます。追加リクエストに新しいテーマを入力すると、そのテーマで新たな調査を開始します。

**Q: 「いいえ」以外で終了する方法は？**  
A: 現在は「いいえ」「no」「終了」などの否定応答のみ対応しています。ブラウザウィンドウを閉じることでも終了できますが、ログが不完全になる場合があります。

**Q: 追加リクエストの確認で「いいえ」と答えたら？**  
A: 追加調査はキャンセルされ、「承知しました。調査を終了します。」と表示されてセッションが終了します。

---

## Part 2: 管理者向け仕様リファレンス

### 実装されたタスク

| # | タスク | 状態 |
|---|--------|------|
| 2-3 | WBS 構造（マイルストン・タスク）を UI に表示 | ✅ 実装済 |
| 2-4 | マイルストン到達時に中間成果物をユーザーに共有する | ✅ 実装済 |
| 2-5 | 調査中いつでも CSM への追加リクエスト（テーマ変更・追加指示）を受け付けるループ | ✅ 実装済 |

---

### WBS 表示の仕様（タスク 2-3）

**実装場所**: `src/research_team/orchestrator/coordinator.py` — `_stream_agent_output()`

PM エージェントが生成したテキスト出力は `_stream_agent_output()` 経由で `_notify()` に渡され、`ui.append_agent_message("PM", text)` として UI に表示されます。

```
PMAgent.run() → _stream_agent_output("PM", ...) → _notify("PM", text) → ui.append_agent_message("PM", text)
```

追加の実装は不要でした。PM が WBS を出力する時点で既に UI に流れる仕組みが整っていたため、テストを追加して動作を確認する形で完了しています。

---

### 中間成果物のファイル保存仕様（タスク 2-4）

**実装場所**: `src/research_team/orchestrator/coordinator.py` — `_run_research()` / `_run_specialist_pass()`

プロジェクト有無に関わらず、以下のタイミングで Markdown ファイルが保存され、CSM がファイルパスをチャットに通知します。

| タイミング | ファイル名 | 保存先 |
|---|---|---|
| チーム編成完了後 | `wbs_run{N}_{date}.md` | `artifacts/` |
| スペシャリスト1名完了後 | `specialist_{name}_run{N}_{date}.md` | `artifacts/` |
| Auditor レビュー完了後 | `review_run{N}_iter{N}_{date}.md` | `artifacts/` |
| 品質改善会議後 | `minutes_run{N}_iter{N}_{date}.md` | `artifacts/` |

**保存先ルール:**

| 条件 | 保存先 |
|------|------|
| `ProjectManager` にアクティブプロジェクトあり | `workspace/projects/{projectId}/files/artifacts/` |
| アクティブプロジェクトなし | `workspace/sessions/{sessionId}/artifacts/` |

セッション ID は `run_interactive()` 開始時に `YYYYMMDD_HHMMSS_{topic_slug}` 形式で一度だけ生成され、同一会話内の全 run で共有されます。

**通知フォーマット（CSM）:**

```
📋 WBS を保存しました:
`/path/to/artifacts/wbs_run1_20260416.md`

📄 経済アナリスト の調査結果を保存しました:
`/path/to/artifacts/specialist_経済アナリスト_run1_20260416.md`
```

---

### 追加リクエストループの仕様（タスク 2-5）

**実装場所**: `src/research_team/orchestrator/coordinator.py` — `run_interactive()`

#### フロー概要

```
run_interactive(depth, output_format)
│
├─ [テーマ確認ループ（US-1-3 実装済み）]
│   └─ topic 確定
│
└─ [調査ループ（US-2-5 追加）]
    ├─ ResearchCoordinator.run(ResearchRequest(topic, depth, output_format))
    ├─ CSM → UI: 「調査が完了しました。追加の調査や修正はありますか？」
    ├─ UI ← ユーザー入力: additional
    │
    ├─ _is_negative(additional) == True
    │   └─ CSM → UI: 「ありがとうございました。調査を終了します。」→ ループ脱出
    │
    └─ _is_negative(additional) == False
        ├─ CSM → UI: 「追加リクエスト「{additional}」を受け付けました。続けますか？」
        ├─ UI ← ユーザー入力: confirm
        ├─ _is_affirmative(confirm) == True  → topic = additional → ループ先頭へ
        └─ _is_affirmative(confirm) == False → CSM: 「承知しました。調査を終了します。」→ ループ脱出
```

#### 否定応答として認識される文字列

`_is_negative()` 関数（`coordinator.py`）が以下を否定と判定します：

| パターン | 例 |
|---------|-----|
| `いいえ` を含む | 「いいえ」「いいえ、終了します」 |
| `no` を含む | 「no」「no thanks」 |
| `終了` を含む | 「終了」「調査を終了してください」 |
| `やめ` を含む | 「やめる」「やめてください」 |
| `おわ` を含む | 「おわり」 |

> 判定は小文字正規化後に `in` 演算子で行われます（部分一致）。

---

### アーキテクチャ概要（US-2 追加部分）

```
run_interactive()
│
├─ session_id 生成（YYYYMMDD_HHMMSS_{slug}）
│
└─ [調査ループ]
    ├─ ResearchCoordinator.run(request, session_id)
    │   ├─ PMAgent.run()
    │   │   └─ _stream_agent_output("PM", ...)
    │   │       └─ _notify("PM", text) → ui.append_agent_message("PM", text)  ← WBS 表示 (2-3)
    │   │
    │   ├─ _make_artifact_writer(session_id)   ← 常時有効化（プロジェクト有無を問わず）
    │   │   ├─ プロジェクトあり → ArtifactWriter(project_files_dir / "artifacts")
    │   │   └─ プロジェクトなし → ArtifactWriter.for_session(workspace_dir, session_id)
    │   │
    │   ├─ artifact_writer.write_wbs(...)      ← WBS ファイル保存 (2-4)
    │   │   └─ _notify("CSM", "📋 WBS を保存しました: `{path}`")
    │   │
    │   └─ _run_specialist_pass(artifact_writer=artifact_writer)
    │       └─ [スペシャリストごとに]
    │           ├─ artifact_writer.write_specialist_draft(...)  ← 逐次保存 (2-4)
    │           └─ _notify("CSM", "📄 {name} の調査結果を保存しました: `{path}`")
    │
    └─ [追加リクエスト確認]                                     ← 追加ループ (2-5)
        ├─ ui.append_agent_message("CSM", "追加の調査はありますか？")
        ├─ additional = ui.wait_for_user_message()
        ├─ _is_negative(additional) → break
        └─ _is_affirmative(confirm) → topic = additional → 再ループ
```

---

### テスト手順

#### 単体テスト

```bash
python -m pytest tests/unit/test_coordinator.py tests/unit/test_artifact_writer.py -v -k "wbs or checkpoint or specialist_draft or artifact_writer or negative or additional"
```

対象テスト:

| テスト名 | 検証内容 |
|---------|---------|
| `test_wbs_is_displayed_via_ui` | PM 出力が UI の `append_agent_message` に届く |
| `test_checkpoint_created_after_specialist_pass` | プロジェクトあり時にチェックポイントが作成される |
| `test_specialist_drafts_saved_during_pass` | スペシャリスト完了ごとに `specialist_*.md` が保存され CSM に通知される |
| `test_make_artifact_writer_uses_project_dir_when_active` | プロジェクトあり時は `project_files_dir/artifacts` を使う |
| `test_make_artifact_writer_uses_session_dir_when_no_project` | プロジェクトなし時は `sessions/{id}/artifacts` を使う |
| `test_write_specialist_draft_creates_file` | `ArtifactWriter.write_specialist_draft()` がファイルを作成する |
| `test_for_session_creates_artifacts_dir` | `ArtifactWriter.for_session()` が正しいディレクトリを使う |
| `test_is_negative_recognizes_no` | 否定語が正しく判定される |
| `test_is_negative_does_not_match_affirmative` | 肯定語が否定と誤判定されない |
| `test_run_interactive_additional_request_loop` | 追加リクエストで2回目の調査が実行される |

#### 統合確認（手動）

1. 起動: `python -m research_team.cli.main start --depth standard`
2. テーマ入力 → 「はい」で調査開始
3. チャットに PM の WBS テキストが表示されることを確認
4. 調査完了後に「追加の調査はありますか？」が届くことを確認
5. 「いいえ」で終了 → セッション終了メッセージを確認
6. 別テーマを入力 → 「はい」で追加調査が始まることを確認

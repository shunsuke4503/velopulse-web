VeloPulse 3D Web版 — GitHub / Streamlit Community Cloud / Supabase
==================================================================

このプロジェクトは、提供された fit_training_app.py のFIT読込・区間平均・傾斜計算・重複判定の流れをWebアプリへ移したものです。ローカルExcel台帳の代わりに、ログインした利用者ごとにSupabaseへ保存します。

含まれるファイル
----------------
- app.py: Streamlit Webアプリ
- requirements.txt: Python依存パッケージ
- supabase_storage_setup.sql: 非公開FITバケットとユーザー別アクセス制御の設定
- .streamlit/config.toml: Streamlit表示設定

保存内容とプライバシー
----------------------
- 集計値・区間ごとの平均データは既存のpublic.training_records.summary (JSONB) に保存します。
- FIT原本は非公開のvelopulse-fit-filesバケットへ保存します。オブジェクト名は「ログインユーザーUUID/SHA256.fit」です。
- アプリはanon/publishable keyとログインユーザーのJWTだけを使います。service_role/secret keyは使いません。
- training_recordsのRLSとStorageのポリシーがuser_id/保存パスを検査します。ユーザーが自分の記録を読込・追加・削除できます。
- Supabaseに保存したFIT原本は、区間秒数を変えた後の再集計にも使います。

公開手順
--------
1. Supabase SQL Editorで supabase_storage_setup.sql の内容を実行します。
   既存のtraining_recordsテーブル、RLS、select/insert/update/deleteポリシー、authenticated権限も確認してください。
2. Supabase Project Settings > APIからProject URLとanon/publishable keyを確認します。
   service_roleまたはsecret keyは使わないでください。
3. このZIPを展開し、中のファイルをGitHubリポジトリのルートにアップロードします。リポジトリはPublic/Privateどちらでも構いません。
4. https://share.streamlit.io/ にGitHubアカウントでログインし、Deploy an appを選びます。リポジトリ、ブランチ、app.pyを指定します。
5. Streamlit Cloudのアプリ画面でSettings > Secretsを開き、次の2項目を設定します。

SUPABASE_URL = "https://bbgjdzhjdfhpwspxfgmr.supabase.co"
SUPABASE_ANON_KEY = "Supabaseのanon/publishable key"

6. Streamlitアプリの公開URLをSupabase Authentication > URL ConfigurationのSite URLとRedirect URLsに追加します。
7. 公開URLで新規登録し、確認メール内のリンクを開いてからログインします。FITを追加して、再読み込み後も履歴が残ることを確認してください。
8. 別のメールアドレスでも登録し、先の利用者の履歴が見えないことを確認してください。

ローカル起動
------------
Python 3.11を用意し、ターミナルでこのフォルダに移動して次を実行します。

    pip install -r requirements.txt
    streamlit run app.py

ローカル設定は `.streamlit/secrets.toml` に次の形式で保存できます（このファイルはGitHubにアップロードしないでください）。

    SUPABASE_URL = "https://bbgjdzhjdfhpwspxfgmr.supabase.co"
    SUPABASE_ANON_KEY = "Supabaseのanon/publishable key"

主な操作
--------
- 区間平均: 初期値は2分です。別の区間に変更したら「保存済みFITをこの区間で再集計」を押します。
- FIT追加: 同一ユーザー内でSHA-256が一致するファイルは重複としてスキップします。
- 絞り込み: 期間、パワー、ケイデンス、心拍、傾斜、気温、ライド時間を指定できます。
- 3Dグラフ: ケイデンス・心拍・パワーを表示します。心拍がない記録は経過時間をY軸にします。
- CSV/Excel: 現在の絞り込み結果を書き出します。
- 削除: ライドの集計行と、対応するFIT原本を削除します。

制限
----
- FIT原本のアップロード上限は1ファイル50 MBです。
- FIT区間平均をJSONBに保存するため、非常に長い記録を大量に蓄積する場合は専用の区間テーブルに分割すると扱いやすくなります。
- Supabase Authのメール確認が有効な状態を想定しています。
- このZIPはアプリのソースと設定手順です。GitHubへの配置やStreamlit Cloudへの公開作業はまだ実行していません。

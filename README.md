# chotgun
a broker script with multi-ponder feature.  works with a USI shogi engine and a GUI like Shogidokoro.

## chotgun.py
- USI将棋エンジンと将棋所のようなGUIの間に入るブローカープログラムです。python3 で動作します。
- スクリプトと同じディレクトリに hosts.txt というファイルを用意して、各行に一つずつ、USIエンジンのあるサーバのアドレスを指定してください。
- hosts.txt の行数分、USIエンジンを起動します。"localhost"でも構いませんし、同じアドレスを複数行に書いても構いません。
- サーバとはSSHで接続します。パスワード無しでアクセスするために、予め公開鍵の設定が必要です。
- デバッグ用に各サーバの出力を全部中継するので、将棋所の表示がとても汚くなります…
- aki.さんの[USIGameRunner](https://github.com/ak110/USIGameRunner)を大変参考にさせていただきました。

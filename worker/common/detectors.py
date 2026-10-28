"""検出器の名前から実装を選ぶ（重いライブラリは使うときだけ読み込む）。

mediapipe 系と rfdetr 系は依存パッケージが衝突しやすく、イメージを分けているので、
どちらか一方しか入っていなくても動くようにしてある。
"""


def make_detector(name, min_score):
    if name.startswith("rfdetr_"):
        from common.detector_rfdetr import RFDETRDetector
        return RFDETRDetector(name, min_score)
    from common.detector_mediapipe import MediaPipeDetector
    return MediaPipeDetector(name, min_score)

// 点レイヤー（駅・学校・地価公示・認可保育所）の共通の形。クリックは app.ts でまとめて受け、
// 直前にクリックした1地点だけを右の欄に出す（重なっている地点は一覧から選ぶ）。
export interface PointLayer {
  /** クリック判定に使う円のレイヤー */
  layer: string;
  /** 一覧で見せる種類名（駅・学校・地価公示・認可保育所） */
  kind: string;
  visible(): boolean;
  /** 地点を選ぶ（null で閉じる） */
  show(id: string | null): void;
  /** 右の欄に地点の情報を出しているか */
  isOpen(): boolean;
}

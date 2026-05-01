from __future__ import annotations

APP_STYLESHEET = """
* {
  font-family: "Inter", "Segoe UI", "Arial", sans-serif;
  font-size: 14px;
}

QWidget {
  background: #F9FAFB;
  color: #111827;
}

QLabel#pageTitle {
  font-size: 20px;
  font-weight: 600;
  color: #111827;
  padding: 4px 0 8px 0;
}

QFrame[card="true"] {
  background: #FFFFFF;
  border: 1px solid #E5E7EB;
  border-radius: 14px;
}

QFrame#stdPanel {
  background: #FFFFFF;
  border: 1px solid #E5E7EB;
  border-radius: 12px;
}

QFrame#stdCard {
  background: #FFFFFF;
  border: 1px solid #D1D5DB;
  border-left: 1px solid #D1D5DB;
  border-radius: 12px;
}

QFrame#stdCard[variant="focus"] {
  background: #EFF6FF;
  border: 1px solid #BFDBFE;
  border-left: 4px solid #93C5FD;
}

QFrame#stdCard[variant="related"] {
  background: #F0FDFA;
  border: 1px solid #CCFBF1;
  border-left: 3px solid #99F6E4;
}

QLabel#stdCardTitle {
  font-size: 14px;
  font-weight: 700;
  color: #111827;
  background: transparent;
}

QLabel#stdCardTitle[tone="focus"] {
  color: #1E3A8A;
}

QLabel#stdCardTitle[tone="related"] {
  color: #134E4A;
}

QLabel#stdBadge {
  color: #374151;
  background: rgba(148, 163, 184, 28);
  border: 1px solid #E5E7EB;
  border-radius: 10px;
  padding: 2px 8px;
  font-size: 11px;
  font-weight: 700;
}

QLabel#stdBadge[kind="focus"] {
  color: #1E3A8A;
  background: rgba(37, 99, 235, 24);
  border: 1px solid #BFDBFE;
}

QLabel#stdBadge[kind="related"] {
  color: #115E59;
  background: rgba(20, 184, 166, 20);
  border: 1px solid #99F6E4;
}

QLabel#stdBadge[kind="success"] {
  color: #166534;
  background: rgba(34, 197, 94, 24);
  border: 1px solid #BBF7D0;
}

QLabel#stdBadge[kind="warning"] {
  color: #92400E;
  background: rgba(245, 158, 11, 26);
  border: 1px solid #FDE68A;
}

QLabel#stdBadge[kind="danger"] {
  color: #B91C1C;
  background: rgba(239, 68, 68, 22);
  border: 1px solid #FECACA;
}

QToolButton#stdActionButton {
  color: #1F2937;
  background: #F3F4F6;
  border: 1px solid #E5E7EB;
  border-radius: 8px;
  padding: 2px 8px;
  font-size: 11px;
  font-weight: 700;
}

QToolButton#stdActionButton:hover {
  background: #E5E7EB;
}

QToolButton#stdActionButton:disabled {
  color: #9CA3AF;
  background: #F9FAFB;
  border: 1px solid #E5E7EB;
}

QPushButton#stdSelectableChip {
  color: #475569;
  background: #F4F7FB;
  border: 1px solid #D6DFEA;
  border-radius: 10px;
  padding: 6px 10px;
  text-align: left;
  font-size: 12px;
  font-weight: 600;
}

QPushButton#stdSelectableChip[chipCompact="true"],
QPushButton#stdSelectableChip[chipCompact=true] {
  border-radius: 8px;
  padding: 3px 8px;
  font-size: 11px;
}

QPushButton#stdSelectableChip[chipActive="true"],
QPushButton#stdSelectableChip[chipActive=true] {
  color: #355985;
  background: #EAF2FF;
  border: 1px solid #C8DDF8;
}

QPushButton#stdSelectableChip[chipSelected="true"],
QPushButton#stdSelectableChip[chipSelected=true] {
  border: 2px solid #5C8ED8;
  padding: 5px 9px;
}

QPushButton#stdSelectableChip[chipCompact="true"][chipSelected="true"],
QPushButton#stdSelectableChip[chipCompact="true"][chipSelected=true],
QPushButton#stdSelectableChip[chipCompact=true][chipSelected="true"],
QPushButton#stdSelectableChip[chipCompact=true][chipSelected=true] {
  padding: 2px 7px;
}

QPushButton#stdSelectableChip[chipTone="success"][chipActive="true"],
QPushButton#stdSelectableChip[chipTone="success"][chipActive=true] {
  color: #2E6C50;
  background: #EDF7F1;
  border-color: #CFE5D8;
}

QPushButton#stdSelectableChip[chipTone="warning"][chipActive="true"],
QPushButton#stdSelectableChip[chipTone="warning"][chipActive=true] {
  color: #846536;
  background: #FAF5E8;
  border-color: #EADBB8;
}

QPushButton#stdSelectableChip[chipTone="danger"][chipActive="true"],
QPushButton#stdSelectableChip[chipTone="danger"][chipActive=true] {
  color: #9A4E61;
  background: #FBEFF2;
  border-color: #EBCDD6;
}

QPushButton#stdSelectableChip:hover {
  background: #EDF3FA;
  border-color: #C8D5E4;
}

QPushButton#stdSelectableChip:disabled {
  color: #94A3B8;
  background: #F8FAFC;
  border-color: #E2E8F0;
}

QTextBrowser#stdTextSourceView {
  background: #FFFFFF;
  color: #111827;
  border: 1px solid #E5E7EB;
  border-radius: 10px;
  padding: 6px;
  selection-background-color: #C7D2FE;
}

QFrame#appHeader {
  background: #FFFFFF;
  border-bottom: 1px solid #E5E7EB;
}

QFrame#brandIcon {
  background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #3B82F6, stop:0.5 #8B5CF6, stop:1 #EC4899);
  border-radius: 12px;
}

QLabel#brandTitle {
  font-weight: 700;
  color: #111827;
}

QLabel#brandSubtitle {
  color: #6B7280;
  font-size: 11px;
}

QLabel#appVersion {
  color: #6B7280;
  font-size: 11px;
}

QFrame#statusBar {
  background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 rgba(59, 130, 246, 0.08), stop:0.5 rgba(139, 92, 246, 0.08), stop:1 rgba(236, 72, 153, 0.08));
  border-top: 1px solid #E5E7EB;
}

QLabel#statusText {
  color: #6B7280;
}

QLabel#statusMeta {
  color: #6B7280;
}

QLabel#statusBrand {
  color: #8B5CF6;
  font-weight: 600;
}

QGroupBox {
  background: #FFFFFF;
  border: 1px solid #E5E7EB;
  border-radius: 14px;
  margin-top: 12px;
  padding: 12px;
}

QGroupBox::title {
  subcontrol-origin: margin;
  left: 12px;
  top: 6px;
  padding: 0 4px;
  color: #111827;
  font-weight: 600;
}

QGroupBox[drawerPlain="true"],
QGroupBox[drawerPlain=true] {
  background: transparent;
  border: 0;
  margin-top: 0;
  padding: 0;
}

QGroupBox[drawerPlain="true"]::title,
QGroupBox[drawerPlain=true]::title {
  subcontrol-origin: margin;
  left: 0;
  top: 0;
  padding: 0 0 2px 0;
}

QLineEdit,
QTextEdit,
QComboBox,
QListWidget {
  background: #FFFFFF;
  border: 1px solid #E5E7EB;
  border-radius: 10px;
  padding: 6px;
  selection-background-color: #C7D2FE;
}

QTextEdit#logView {
  font-family: "JetBrains Mono", "Consolas", "Courier New", monospace;
  font-size: 12px;
  background: #F3F4F6;
}

QComboBox::drop-down {
  border: none;
}

QComboBox QAbstractItemView {
  background: #FFFFFF;
  border: 1px solid #E5E7EB;
  selection-background-color: #E0E7FF;
  selection-color: #111827;
}

QListWidget::item:selected {
  background: #E0E7FF;
  color: #111827;
}

QListWidget#historyMeetingsList::item:selected,
QListWidget#historyMeetingsList::item:selected:active,
QListWidget#historyMeetingsList::item:selected:!active {
  background: transparent;
  border: none;
}

QListWidget#settingsMultiSelectList,
QListWidget#projectsMultiSelectList {
  background: #FFFFFF;
  border: 1px solid #CBD5E1;
  border-radius: 10px;
}

QListWidget#settingsMultiSelectList::item,
QListWidget#projectsMultiSelectList::item {
  padding: 4px 4px;
  border-radius: 6px;
}

QListWidget#settingsMultiSelectList::item:hover,
QListWidget#projectsMultiSelectList::item:hover {
  background: #F1F5F9;
}

QListWidget#settingsMultiSelectList::indicator,
QListWidget#projectsMultiSelectList::indicator,
QListView::indicator {
  width: 18px;
  height: 18px;
}

QListWidget#settingsMultiSelectList::indicator:unchecked,
QListWidget#projectsMultiSelectList::indicator:unchecked,
QListView::indicator:unchecked {
  border: 2px solid #64748B;
  border-radius: 4px;
  background: #FFFFFF;
}

QListWidget#settingsMultiSelectList::indicator:checked,
QListWidget#projectsMultiSelectList::indicator:checked,
QListView::indicator:checked {
  border: 2px solid #2563EB;
  border-radius: 4px;
  background: #2563EB;
}

QPushButton {
  background: #FFFFFF;
  color: #374151;
  border: 1px solid #E5E7EB;
  border-radius: 10px;
  padding: 6px 12px;
}

QPushButton:hover {
  background: #F3F4F6;
}

QPushButton:disabled {
  color: #9CA3AF;
  background: rgba(148, 163, 184, 20);
  border-color: #E5E7EB;
}

QPushButton#pipelineRunButton {
  background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #3B82F6, stop:0.5 #8B5CF6, stop:1 #EC4899);
  color: #FFFFFF;
  border: none;
  font-weight: 800;
}

QPushButton#pipelineRunButton:disabled {
  background: transparent;
  color: #9CA3AF;
  border: 2px solid #E5E7EB;
}

QPushButton#pipelineRunButton:hover {
  background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #2563EB, stop:0.5 #7C3AED, stop:1 #DB2777);
}

QPushButton#pipelinePauseButton {
  background: transparent;
  color: #0EA5E9;
  border: 2px solid #0EA5E9;
  font-weight: 700;
}

QPushButton#pipelinePauseButton:hover {
  background: transparent;
  color: #0284C7;
  border: 2px solid #0284C7;
}

QPushButton#pipelinePauseButton:disabled {
  background: transparent;
  color: #9CA3AF;
  border: 2px solid #E5E7EB;
}

QPushButton#pipelineStopButton {
  background: transparent;
  color: #EF4444;
  border: 2px solid #EF4444;
  font-weight: 700;
}

QPushButton#pipelineStopButton:hover {
  background: transparent;
  color: #DC2626;
  border: 2px solid #DC2626;
}

QPushButton#pipelineStopButton:disabled {
  background: transparent;
  color: #9CA3AF;
  border: 2px solid #E5E7EB;
}

QScrollBar:vertical {
  background: transparent;
  width: 10px;
  margin: 4px 2px;
}

QScrollBar::handle:vertical {
  background: #CBD5E1;
  border-radius: 6px;
  min-height: 24px;
}

QScrollBar::handle:vertical:hover {
  background: #94A3B8;
}

QScrollBar:horizontal {
  background: transparent;
  height: 10px;
  margin: 2px 4px;
}

QScrollBar::handle:horizontal {
  background: #CBD5E1;
  border-radius: 6px;
  min-width: 24px;
}

QScrollBar::handle:horizontal:hover {
  background: #94A3B8;
}

QScrollBar::add-line,
QScrollBar::sub-line {
  width: 0;
  height: 0;
}

QScrollBar::add-page,
QScrollBar::sub-page {
  background: transparent;
}

QFrame#audioControlBar {
  background: #FFFFFF;
  border: 1px solid #E5E7EB;
  border-radius: 12px;
}

QToolButton#audioControlButton {
  background: #F3F4F6;
  border: 1px solid #E5E7EB;
  border-radius: 10px;
  padding: 4px 10px;
  font-weight: 600;
}

QToolButton#audioControlButton:hover {
  background: #E5E7EB;
}

QSlider#audioSeekSlider::groove:horizontal {
  height: 6px;
  background: #E5E7EB;
  border-radius: 3px;
}

QSlider#audioSeekSlider::sub-page:horizontal {
  background: #60A5FA;
  border-radius: 3px;
}

QSlider#audioSeekSlider::add-page:horizontal {
  background: #E5E7EB;
  border-radius: 3px;
}

QSlider#audioSeekSlider::handle:horizontal {
  background: #2563EB;
  width: 14px;
  margin: -4px 0;
  border-radius: 7px;
}

QFrame#pipelineTileV2 {
  background: #FFFFFF;
  border: 1px solid #E5E7EB;
  border-radius: 12px;
}

QFrame#pipelineTileV2[selected="true"],
QFrame#pipelineTileV2[selected=true] {
  border: 2px solid #2563EB;
}

QFrame#pipelineTileV2[attention="true"],
QFrame#pipelineTileV2[attention=true] {
  border: 2px solid #60A5FA;
}

QLabel#pipelineTileName {
  font-weight: 700;
}

QLabel#pipelineTileStatusBadge,
QLabel#pipelineTileProgressBadge {
  font-size: 11px;
  font-weight: 700;
  border-radius: 8px;
  padding: 2px 8px;
  min-height: 18px;
}

QLabel#pipelineTileStatusBadge[state="idle"],
QLabel#pipelineTileStatusBadge[state="disabled"] {
  color: #55657A;
  background: #F4F7FB;
  border: 1px solid #D6DFEA;
}

QLabel#pipelineTileStatusBadge[state="ready"],
QLabel#pipelineTileStatusBadge[state="running"] {
  color: #395F8E;
  background: #EDF4FF;
  border: 1px solid #C8DDF8;
}

QLabel#pipelineTileStatusBadge[state="completed"] {
  color: #2E6C50;
  background: #EDF7F1;
  border: 1px solid #CFE5D8;
}

QLabel#pipelineTileStatusBadge[state="skipped"] {
  color: #846536;
  background: #FAF5E8;
  border: 1px solid #EADBB8;
}

QLabel#pipelineTileStatusBadge[state="failed"] {
  color: #9A4E61;
  background: #FBEFF2;
  border: 1px solid #EBCDD6;
}

QLabel#pipelineTileProgressBadge {
  color: #395F8E;
  background: #EDF4FF;
  border: 1px solid #C8DDF8;
}

QLabel#pipelineTileProgressBadge[state="idle"],
QLabel#pipelineTileProgressBadge[state="disabled"] {
  color: #55657A;
  background: #F4F7FB;
  border: 1px solid #D6DFEA;
}

QLabel#pipelineTileProgressBadge[state="completed"] {
  color: #2E6C50;
  background: #EDF7F1;
  border: 1px solid #CFE5D8;
}

QLabel#pipelineTileProgressBadge[state="failed"] {
  color: #9A4E61;
  background: #FBEFF2;
  border: 1px solid #EBCDD6;
}

QToolButton#pipelineTileActionButton {
  color: #1F2937;
  background: #F3F4F6;
  border: 1px solid #E5E7EB;
  border-radius: 8px;
  padding: 2px 8px;
  font-size: 11px;
  font-weight: 700;
}

QToolButton#pipelineTileActionButton:hover {
  background: #E5E7EB;
}

QToolButton#pipelineTileActionButton:disabled {
  color: #9CA3AF;
  background: #F9FAFB;
  border: 1px solid #E5E7EB;
}

QListWidget#artifactsKindList {
  background: transparent;
  border: none;
  padding: 0;
}

QListWidget#artifactsKindList::item {
  color: #374151;
  background: #F3F4F6;
  border: 1px solid #E5E7EB;
  border-radius: 8px;
  padding: 6px 10px;
  margin: 3px 0;
  font-size: 11px;
  font-weight: 700;
}

QListWidget#artifactsKindList::item:hover:!selected {
  background: #E5E7EB;
}

QListWidget#artifactsKindList::item:selected {
  color: #1D4ED8;
  background: rgba(59, 130, 246, 28);
  border: 1px solid #93C5FD;
}

QListWidget#transcriptSegmentsList {
  background: rgba(255, 255, 255, 220);
  border: 1px solid #D1D5DB;
  border-radius: 10px;
}

QListWidget#transcriptSegmentsList::item {
  background: rgba(255, 255, 255, 204);
  border: 1px solid #E5E7EB;
  border-radius: 8px;
  margin: 3px 4px;
  padding: 6px 8px;
}

QListWidget#transcriptSegmentsList::item:hover:!selected {
  background: rgba(148, 163, 184, 18);
  border-color: #CBD5E1;
}

QListWidget#transcriptSegmentsList::item:selected,
QListWidget#transcriptSegmentsList::item:selected:active,
QListWidget#transcriptSegmentsList::item:selected:!active {
  color: #1D4ED8;
  background: rgba(59, 130, 246, 24);
  border: 1px solid #93C5FD;
}

QTabBar#artifactKindTabBar::tab {
  color: #55657A;
  background: #F4F7FB;
  border: 1px solid #D6DFEA;
  border-radius: 8px;
  padding: 4px 10px;
  margin-right: 6px;
  min-width: 120px;
  max-width: 240px;
  font-size: 11px;
  font-weight: 700;
}

QTabBar#artifactKindTabBar::tab:hover:!selected {
  background: #EDF3FA;
  border-color: #C8D5E4;
}

QTabBar#artifactKindTabBar::tab:selected {
  color: #40556F;
  background: #EAF1F8;
  border: 1px solid #BFD1E4;
}

QTabBar#artifactKindTabBar[kindPalette="transcript"]::tab {
  color: #395F8E;
  background: #F1F6FF;
  border: 1px solid #C8DDF8;
}

QTabBar#artifactKindTabBar[kindPalette="transcript"]::tab:hover:!selected {
  background: #E7F1FF;
  border-color: #B7D4F4;
}

QTabBar#artifactKindTabBar[kindPalette="transcript"]::tab:selected {
  color: #355985;
  background: #E3EEFF;
  border: 1px solid #B7D4F4;
}

QTabBar#artifactKindTabBar[kindPalette="summary"]::tab {
  color: #2E6C50;
  background: #F1F9F3;
  border: 1px solid #CFE5D8;
}

QTabBar#artifactKindTabBar[kindPalette="summary"]::tab:hover:!selected {
  background: #E7F4EC;
  border-color: #BFD8CA;
}

QTabBar#artifactKindTabBar[kindPalette="summary"]::tab:selected {
  color: #2A644B;
  background: #E2F0E8;
  border: 1px solid #BFD8CA;
}

QTabBar#artifactKindTabBar[activeKind="false"]::tab:selected {
  color: #55657A;
  background: #F4F7FB;
  border: 1px solid #D6DFEA;
}

QTabBar#artifactKindTabBar[kindPalette="transcript"][activeKind="false"]::tab:selected {
  color: #395F8E;
  background: #F1F6FF;
  border: 1px solid #C8DDF8;
}

QTabBar#artifactKindTabBar[kindPalette="summary"][activeKind="false"]::tab:selected {
  color: #2E6C50;
  background: #F1F9F3;
  border: 1px solid #CFE5D8;
}

QLabel#artifactKindRowTitle {
  font-size: 11px;
  font-weight: 700;
  border-radius: 10px;
  padding: 4px 10px;
  border: 1px solid #D6DFEA;
  color: #55657A;
  background: #F4F7FB;
}

QLabel#artifactKindRowTitle[kindPalette="transcript"] {
  color: #395F8E;
  background: #EDF4FF;
  border: 1px solid #C8DDF8;
}

QLabel#artifactKindRowTitle[kindPalette="summary"] {
  color: #2E6C50;
  background: #EDF7F1;
  border: 1px solid #CFE5D8;
}

QToolButton#artifactAliasButton {
  color: #55657A;
  background: #F6F9FD;
  border: 1px solid #D6DFEA;
  border-radius: 8px;
  padding: 3px 9px;
  font-size: 11px;
  font-weight: 600;
}

QToolButton#artifactAliasButton:hover {
  background: #EDF3FA;
  border-color: #C8D5E4;
}

QToolButton#artifactAliasButton:checked {
  color: #40556F;
  background: #EAF1F8;
  border-color: #BFD1E4;
}

QToolButton#artifactAliasButton[kindPalette="transcript"] {
  color: #395F8E;
  background: #F1F6FF;
  border-color: #C8DDF8;
}

QToolButton#artifactAliasButton[kindPalette="transcript"]:hover {
  background: #E7F1FF;
}

QToolButton#artifactAliasButton[kindPalette="transcript"]:checked {
  color: #355985;
  background: #E3EEFF;
  border-color: #B7D4F4;
}

QToolButton#artifactAliasButton[kindPalette="summary"] {
  color: #2E6C50;
  background: #F1F9F3;
  border-color: #CFE5D8;
}

QToolButton#artifactAliasButton[kindPalette="summary"]:hover {
  background: #E7F4EC;
}

QToolButton#artifactAliasButton[kindPalette="summary"]:checked {
  color: #2A644B;
  background: #E2F0E8;
  border-color: #BFD8CA;
}

QFrame#stageSettingsDrawer {
  background: #FFFFFF;
  border: 1px solid #E5E7EB;
  border-radius: 14px;
}

QLabel#stageSettingsTitle {
  font-weight: 700;
}

QLabel#panelTitle {
  font-weight: 700;
}

QFrame#pluginHeroCard {
  background: qlineargradient(x1:0, y1:0, x2:1, y2:0.8, stop:0 #FFFFFF, stop:1 #EEF2FF);
  border: 1px solid #E5E7EB;
  border-radius: 16px;
}

QLabel#pluginHeroTitle {
  font-size: 18px;
  font-weight: 800;
  color: #111827;
}

QLabel#pluginHeroTagline {
  font-size: 12px;
  font-weight: 700;
  color: #1D4ED8;
}

QLabel#pluginHeroBody {
  font-size: 12px;
  color: #374151;
}

QLabel#pluginHowTo {
  font-size: 12px;
  color: #374151;
}

QLabel#searchMatchesLabel {
  color: #6B7280;
  font-size: 11px;
}

QLabel#pipelineMetaLabel {
  color: #6B7280;
  font-size: 11px;
}

QFrame#pipelineActivityTile {
  background: #FFFFFF;
  border: 1px solid #E5E7EB;
  border-radius: 10px;
}

QLabel#pipelineActivityPrimary {
  color: #374151;
  font-size: 12px;
  font-weight: 700;
}

QLabel#listTileTitle {
  font-size: 13px;
  font-weight: 700;
  color: #111827;
}

QLabel#listTileSubtitle {
  font-size: 11px;
  color: #374151;
  font-weight: 600;
}

QLabel#listTileMetaPrimary {
  font-size: 11px;
  color: #374151;
  font-weight: 600;
}

QLabel#listTileMeta {
  font-size: 11px;
  color: #6B7280;
}

QFrame#listTileCard {
  background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #FFFFFF, stop:1 #F8FAFC);
  border: 1px solid #E5E7EB;
  border-radius: 14px;
}

QFrame#listTileCard:hover {
  background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #FFFFFF, stop:1 #EFF6FF);
  border: 1px solid #BFDBFE;
}

QFrame#listTileCard[selected="true"],
QFrame#listTileCard[selected=true] {
  background: rgba(37, 99, 235, 22);
  border: 2px solid #2563EB;
}

QFrame#listTileCard[pressed="true"] {
  border: 2px solid #1D4ED8;
}

QFrame#historyItemCard {
  border: 1px solid #E5E7EB;
  border-radius: 12px;
  background: #FFFFFF;
}

QFrame#historyItemCard[selected="true"],
QFrame#historyItemCard[selected=true] {
  border: 1px solid #BFDBFE;
  background: #EEF2FF;
}

QLabel#historyItemTitle {
  font-size: 13px;
  font-weight: 700;
  color: #111827;
}

QLabel#historyItemMetaPrimary {
  font-size: 11px;
  color: #374151;
  font-weight: 600;
}

QLabel#historyItemMeta {
  font-size: 11px;
  color: #6B7280;
}

QToolButton#historyItemRename {
  color: #1F2937;
  font-weight: 700;
  background: #EEF2FF;
  border: 1px solid #C7D2FE;
  border-radius: 8px;
  padding: 2px 8px;
}

QToolButton#historyItemRename:hover {
  background: #E0E7FF;
  border: 1px solid #A5B4FC;
}

QToolButton#historyItemRename:disabled {
  color: #9CA3AF;
  background: #F3F4F6;
  border: 1px solid #E5E7EB;
}

QToolButton#historyItemRerun {
  color: #1D4ED8;
  font-weight: 700;
  background: #DBEAFE;
  border: 1px solid #BFDBFE;
  border-radius: 8px;
  padding: 2px 8px;
}

QToolButton#historyItemRerun:disabled {
  color: #9CA3AF;
  background: #F3F4F6;
  border: 1px solid #E5E7EB;
}

QToolButton#historyItemDelete {
  color: #B91C1C;
  font-weight: 700;
  background: #FEE2E2;
  border: 1px solid #FECACA;
  border-radius: 8px;
  padding: 2px 8px;
}

QToolButton#historyItemDelete:hover {
  background: #FECACA;
  border: 1px solid #FCA5A5;
}

QFrame#stageTile {
  background: #FFFFFF;
  border: 1px solid #E5E7EB;
  border-radius: 12px;
}

QFrame#modelCard {
  background: #FFFFFF;
  border: 1px solid #E5E7EB;
  border-radius: 12px;
}

QLabel#stageStatus {
  font-size: 11px;
  font-weight: 600;
}

QFrame#stageInspectorHeader {
  background: #FFFFFF;
  border: 1px solid #E5E7EB;
  border-radius: 10px;
}

QLabel#stageInspectorTitle {
  font-weight: 700;
}

QLabel#stageInspectorStatus {
  color: #6B7280;
}

QLabel#stageInspectorMeta {
  color: #9CA3AF;
  font-size: 11px;
}

QDockWidget::title {
  background: #F3F4F6;
  padding: 6px;
  border-bottom: 1px solid #E5E7EB;
}

QTabWidget::pane {
  border: 1px solid #E5E7EB;
  border-top: none;
  background: #F9FAFB;
}

QTabBar::tab {
  background: #FFFFFF;
  color: #6B7280;
  padding: 10px 16px;
  border: none;
}

QTabBar::tab:selected {
  color: #111827;
  border-bottom: 2px solid #8B5CF6;
}

QScrollArea {
  border: none;
}

QProgressBar {
  border: 1px solid #E5E7EB;
  border-radius: 8px;
  background: #F3F4F6;
  height: 12px;
  text-align: center;
}

QProgressBar::chunk {
  background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #3B82F6, stop:0.5 #8B5CF6, stop:1 #EC4899);
  border-radius: 8px;
}

QCheckBox {
  color: #374151;
}

QCheckBox::indicator {
  width: 16px;
  height: 16px;
}

QCheckBox::indicator:unchecked {
  border: 1px solid #D1D5DB;
  border-radius: 4px;
  background: #FFFFFF;
}

QCheckBox::indicator:checked {
  border: 1px solid #8B5CF6;
  background: #8B5CF6;
}

/* Shared semi-transparent surface scale for light themes */
QFrame[card="true"],
QFrame#stdPanel,
QFrame#stdCard,
QFrame#pipelineTileV2,
QFrame#stageSettingsDrawer,
QFrame#historyItemCard,
QFrame#stageTile,
QFrame#modelCard,
QFrame#stageInspectorHeader,
QFrame#audioControlBar,
QFrame#listTileCard,
QFrame#pipelineActivityTile,
QGroupBox {
  background: rgba(255, 255, 255, 218);
  border-color: #D1D5DB;
}

QLineEdit,
QTextEdit,
QComboBox,
QListWidget,
QTextBrowser#stdTextSourceView,
QComboBox QAbstractItemView {
  background: rgba(255, 255, 255, 226);
  border-color: #D1D5DB;
}

QPushButton,
QToolButton#audioControlButton,
QToolButton#pipelineTileActionButton,
QToolButton#stdActionButton {
  background: rgba(148, 163, 184, 24);
  border-color: #CBD5E1;
}

QPushButton:hover,
QToolButton#audioControlButton:hover,
QToolButton#pipelineTileActionButton:hover,
QToolButton#stdActionButton:hover {
  background: rgba(148, 163, 184, 40);
}

QPushButton:disabled {
  background: rgba(148, 163, 184, 18);
  border-color: #D1D5DB;
}

QTabBar::tab,
QTabBar#artifactKindTabBar::tab,
QListWidget#artifactsKindList::item {
  background: rgba(255, 255, 255, 208);
  border-color: #D1D5DB;
}

QToolButton#historyItemRename {
  background: rgba(99, 102, 241, 26);
  border-color: #C7D2FE;
}

QToolButton#historyItemRerun {
  background: rgba(59, 130, 246, 24);
  border-color: #BFDBFE;
}

QToolButton#historyItemDelete {
  background: rgba(239, 68, 68, 22);
  border-color: #FECACA;
}
"""

DEFAULT_THEME_ID = "light"
THEME_IDS = ("light", "dark", "light_mono", "dark_mono")

_THEME_OVERRIDES = {
    "dark": """
QWidget {
  background: #0F172A;
  color: #E2E8F0;
}

QFrame[card="true"],
QFrame#appHeader,
QGroupBox,
QFrame#pipelineTileV2,
QFrame#stageSettingsDrawer,
QFrame#stageTile,
QFrame#modelCard,
QFrame#audioControlBar,
QFrame#stageInspectorHeader,
QFrame#listTileCard {
  background: #111827;
  border-color: #334155;
}

QFrame#listTileCard:hover {
  background: #172036;
  border-color: #334155;
}

QFrame#listTileCard[selected="true"],
QFrame#listTileCard[selected=true],
QFrame#listTileCard[selected="true"]:hover,
QFrame#listTileCard[selected=true]:hover {
  background: #1E293B;
  border: 2px solid #38BDF8;
}

QFrame#listTileCard[pressed="true"] {
  border: 2px solid #0EA5E9;
}

QFrame#pipelineTileV2[selected="true"],
QFrame#pipelineTileV2[selected=true] {
  border: 2px solid #38BDF8;
}

QFrame#pipelineTileV2[attention="true"],
QFrame#pipelineTileV2[attention=true] {
  border: 2px solid #0EA5E9;
}

QFrame#historyItemCard {
  background: #111827;
  border-color: #334155;
}

QFrame#historyItemCard[selected="true"],
QFrame#historyItemCard[selected=true] {
  background: rgba(51, 65, 85, 178);
  border-color: #64748B;
}

QFrame#pluginHeroCard {
  background: qlineargradient(x1:0, y1:0, x2:1, y2:0.8, stop:0 rgba(17, 24, 39, 210), stop:1 rgba(30, 41, 59, 210));
  border: 1px solid #334155;
  border-radius: 16px;
}

QLabel#pluginHeroTagline {
  color: #93C5FD;
}

QLabel#pluginHeroBody,
QLabel#pluginHowTo {
  color: #CBD5E1;
}

QFrame#stdPanel {
  background: #111827;
  border-color: #334155;
}

QFrame#stdCard {
  background: #111827;
  border: 1px solid #334155;
  border-left: 1px solid #334155;
}

QFrame#stdCard[variant="focus"] {
  background: #172554;
  border: 1px solid #3B82F6;
  border-left: 4px solid #60A5FA;
}

QFrame#stdCard[variant="related"] {
  background: #042F2E;
  border: 1px solid #14B8A6;
  border-left: 3px solid #2DD4BF;
}

QLabel#stdCardTitle {
  color: #F8FAFC;
}

QLabel#stdCardTitle[tone="focus"] {
  color: #BFDBFE;
}

QLabel#stdCardTitle[tone="related"] {
  color: #99F6E4;
}

QLabel#stdBadge {
  color: #E2E8F0;
  background: rgba(11, 18, 32, 170);
  border: 1px solid #334155;
}

QLabel#stdBadge[kind="focus"] {
  color: #BFDBFE;
  background: rgba(30, 58, 138, 170);
  border: 1px solid #3B82F6;
}

QLabel#stdBadge[kind="related"] {
  color: #99F6E4;
  background: rgba(19, 78, 74, 170);
  border: 1px solid #2DD4BF;
}

QLabel#stdBadge[kind="success"] {
  color: #86EFAC;
  background: rgba(20, 83, 45, 170);
  border: 1px solid #22C55E;
}

QLabel#stdBadge[kind="warning"] {
  color: #FCD34D;
  background: rgba(120, 53, 15, 170);
  border: 1px solid #F59E0B;
}

QLabel#stdBadge[kind="danger"] {
  color: #FCA5A5;
  background: rgba(127, 29, 29, 170);
  border: 1px solid #EF4444;
}

QToolButton#stdActionButton {
  background: #0B1220;
  color: #E2E8F0;
  border: 1px solid #334155;
}

QToolButton#stdActionButton:hover {
  background: #1F2937;
  border-color: #475569;
}

QToolButton#stdActionButton:disabled {
  color: #64748B;
  background: #111827;
  border: 1px solid #334155;
}

QPushButton#stdSelectableChip {
  color: #B7C3D6;
  background: rgba(37, 48, 63, 178);
  border: 1px solid #3A4C61;
  border-radius: 10px;
  padding: 6px 10px;
  text-align: left;
  font-size: 12px;
  font-weight: 600;
}

QPushButton#stdSelectableChip[chipCompact="true"],
QPushButton#stdSelectableChip[chipCompact=true] {
  border-radius: 8px;
  padding: 3px 8px;
  font-size: 11px;
}

QPushButton#stdSelectableChip[chipActive="true"],
QPushButton#stdSelectableChip[chipActive=true] {
  color: #C9D9EE;
  background: rgba(52, 74, 102, 178);
  border: 1px solid #55769A;
}

QPushButton#stdSelectableChip[chipSelected="true"],
QPushButton#stdSelectableChip[chipSelected=true] {
  border: 2px solid #7AA6D8;
  padding: 5px 9px;
}

QPushButton#stdSelectableChip[chipCompact="true"][chipSelected="true"],
QPushButton#stdSelectableChip[chipCompact="true"][chipSelected=true],
QPushButton#stdSelectableChip[chipCompact=true][chipSelected="true"],
QPushButton#stdSelectableChip[chipCompact=true][chipSelected=true] {
  padding: 2px 7px;
}

QPushButton#stdSelectableChip[chipTone="success"][chipActive="true"],
QPushButton#stdSelectableChip[chipTone="success"][chipActive=true] {
  color: #B9DDCB;
  background: rgba(34, 56, 47, 178);
  border-color: #4D7366;
}

QPushButton#stdSelectableChip[chipTone="warning"][chipActive="true"],
QPushButton#stdSelectableChip[chipTone="warning"][chipActive=true] {
  color: #E3D2AF;
  background: rgba(70, 58, 33, 176);
  border-color: #8B7A52;
}

QPushButton#stdSelectableChip[chipTone="danger"][chipActive="true"],
QPushButton#stdSelectableChip[chipTone="danger"][chipActive=true] {
  color: #E3B8C4;
  background: rgba(66, 39, 48, 178);
  border-color: #8F5A68;
}

QPushButton#stdSelectableChip:hover {
  background: rgba(45, 58, 76, 190);
  border-color: #4B6079;
}

QPushButton#stdSelectableChip:disabled {
  color: #64748B;
  background: rgba(17, 24, 39, 170);
  border-color: #334155;
}

QTextBrowser#stdTextSourceView {
  background: #0B1220;
  color: #E2E8F0;
  border: 1px solid #334155;
  selection-background-color: #1D4ED8;
}

QLabel#historyItemTitle {
  color: #F8FAFC;
}

QLabel#historyItemMetaPrimary,
QLabel#historyItemMeta {
  color: #94A3B8;
}

QToolButton#historyItemRename,
QToolButton#historyItemRerun,
QToolButton#historyItemDelete {
  color: #E2E8F0;
  background: #1F2937;
  border-color: #334155;
}

QFrame#historyItemCard[selected="true"] QToolButton#historyItemRename,
QFrame#historyItemCard[selected=true] QToolButton#historyItemRename,
QFrame#historyItemCard[selected="true"] QToolButton#historyItemRerun,
QFrame#historyItemCard[selected=true] QToolButton#historyItemRerun,
QFrame#historyItemCard[selected="true"] QToolButton#historyItemDelete,
QFrame#historyItemCard[selected=true] QToolButton#historyItemDelete {
  background: #334155;
  border-color: #64748B;
}

QToolButton#historyItemRename:hover,
QToolButton#historyItemRerun:hover,
QToolButton#historyItemDelete:hover {
  background: #334155;
}

QLineEdit,
QTextEdit,
QComboBox,
QListWidget {
  background: #0B1220;
  color: #E2E8F0;
  border-color: #334155;
  selection-background-color: #1D4ED8;
}

QListWidget#artifactsKindList {
  background: transparent;
  border: none;
}

QListWidget#artifactsKindList::item {
  color: #CBD5E1;
  background: #111827;
  border: 1px solid #334155;
  border-radius: 8px;
  padding: 6px 10px;
  margin: 3px 0;
  font-size: 11px;
  font-weight: 700;
}

QListWidget#artifactsKindList::item:hover:!selected {
  background: #1F2937;
  border-color: #475569;
}

QListWidget#artifactsKindList::item:selected {
  color: #BFDBFE;
  background: rgba(30, 58, 138, 170);
  border: 1px solid #3B82F6;
}

QListWidget#transcriptSegmentsList {
  background: rgba(11, 18, 32, 196);
  border: 1px solid #334155;
  border-radius: 10px;
}

QListWidget#transcriptSegmentsList::item {
  color: #CBD5E1;
  background: rgba(15, 23, 42, 172);
  border: 1px solid #334155;
  border-radius: 8px;
  margin: 3px 4px;
  padding: 6px 8px;
}

QListWidget#transcriptSegmentsList::item:hover:!selected {
  background: rgba(30, 41, 59, 180);
  border-color: #475569;
}

QListWidget#transcriptSegmentsList::item:selected,
QListWidget#transcriptSegmentsList::item:selected:active,
QListWidget#transcriptSegmentsList::item:selected:!active {
  color: #BFDBFE;
  background: rgba(30, 58, 138, 170);
  border: 1px solid #3B82F6;
}

QTabBar#artifactKindTabBar::tab {
  color: #B7C3D6;
  background: rgba(37, 48, 63, 182);
  border: 1px solid #3A4C61;
  border-radius: 8px;
  padding: 4px 10px;
  margin-right: 6px;
  min-width: 120px;
  max-width: 240px;
  font-size: 11px;
  font-weight: 700;
}

QTabBar#artifactKindTabBar::tab:hover:!selected {
  background: rgba(45, 58, 76, 190);
  border-color: #4B6079;
}

QTabBar#artifactKindTabBar::tab:selected {
  color: #C6D4E6;
  background: rgba(55, 70, 90, 188);
  border: 1px solid #5E7693;
}

QTabBar#artifactKindTabBar[kindPalette="transcript"]::tab {
  color: #C9D9EE;
  background: rgba(52, 74, 102, 148);
  border: 1px solid #55769A;
}

QTabBar#artifactKindTabBar[kindPalette="transcript"]::tab:hover:!selected {
  color: #D6E3F2;
  background: rgba(59, 84, 113, 184);
  border-color: #6788AE;
}

QTabBar#artifactKindTabBar[kindPalette="transcript"]::tab:selected {
  color: #D6E3F2;
  background: rgba(59, 84, 113, 184);
  border: 1px solid #6788AE;
}

QTabBar#artifactKindTabBar[kindPalette="summary"]::tab {
  color: #B9DDCB;
  background: rgba(34, 56, 47, 152);
  border: 1px solid #4D7366;
}

QTabBar#artifactKindTabBar[kindPalette="summary"]::tab:hover:!selected {
  color: #CAE8DB;
  background: rgba(39, 66, 54, 182);
  border-color: #628B7D;
}

QTabBar#artifactKindTabBar[kindPalette="summary"]::tab:selected {
  color: #CAE8DB;
  background: rgba(39, 66, 54, 182);
  border: 1px solid #628B7D;
}

QTabBar#artifactKindTabBar[activeKind="false"]::tab:selected {
  color: #B7C3D6;
  background: rgba(37, 48, 63, 182);
  border: 1px solid #3A4C61;
}

QTabBar#artifactKindTabBar[kindPalette="transcript"][activeKind="false"]::tab:selected {
  color: #C9D9EE;
  background: rgba(52, 74, 102, 148);
  border: 1px solid #55769A;
}

QTabBar#artifactKindTabBar[kindPalette="summary"][activeKind="false"]::tab:selected {
  color: #B9DDCB;
  background: rgba(34, 56, 47, 152);
  border: 1px solid #4D7366;
}

QLabel#artifactKindRowTitle {
  color: #B7C3D6;
  background: rgba(37, 48, 63, 178);
  border: 1px solid #3A4C61;
}

QLabel#artifactKindRowTitle[kindPalette="transcript"] {
  color: #C9D9EE;
  background: rgba(52, 74, 102, 178);
  border: 1px solid #55769A;
}

QLabel#artifactKindRowTitle[kindPalette="summary"] {
  color: #B9DDCB;
  background: rgba(34, 56, 47, 178);
  border: 1px solid #4D7366;
}

QToolButton#artifactAliasButton {
  color: #B7C3D6;
  background: rgba(33, 44, 58, 165);
  border: 1px solid #3A4C61;
  border-radius: 8px;
  padding: 3px 9px;
  font-size: 11px;
  font-weight: 600;
}

QToolButton#artifactAliasButton:hover {
  background: rgba(45, 58, 76, 180);
  border-color: #4B6079;
}

QToolButton#artifactAliasButton:checked {
  color: #C6D4E6;
  background: rgba(55, 70, 90, 188);
  border-color: #5E7693;
}

QToolButton#artifactAliasButton[kindPalette="transcript"] {
  color: #C9D9EE;
  background: rgba(52, 74, 102, 148);
  border-color: #55769A;
}

QToolButton#artifactAliasButton[kindPalette="transcript"]:hover,
QToolButton#artifactAliasButton[kindPalette="transcript"]:checked {
  color: #D6E3F2;
  background: rgba(59, 84, 113, 184);
  border-color: #6788AE;
}

QToolButton#artifactAliasButton[kindPalette="summary"] {
  color: #B9DDCB;
  background: rgba(34, 56, 47, 152);
  border-color: #4D7366;
}

QToolButton#artifactAliasButton[kindPalette="summary"]:hover,
QToolButton#artifactAliasButton[kindPalette="summary"]:checked {
  color: #CAE8DB;
  background: rgba(39, 66, 54, 182);
  border-color: #628B7D;
}

QComboBox QAbstractItemView {
  background: #0B1220;
  color: #E2E8F0;
  border: 1px solid #334155;
  selection-background-color: #1D4ED8;
  selection-color: #F8FAFC;
}

QComboBox QAbstractItemView::item {
  background: #0B1220;
  color: #E2E8F0;
}

QComboBox QAbstractItemView::item:hover {
  background: #1F2937;
}

QComboBox QAbstractItemView::item:selected {
  background: #1D4ED8;
  color: #F8FAFC;
}

QLabel#pageTitle,
QLabel#brandTitle,
QLabel#pipelineTileName,
QLabel#stageSettingsTitle,
QLabel#panelTitle,
QLabel#pluginHeroTitle,
QLabel#listTileTitle {
  color: #F8FAFC;
}

QLabel#brandSubtitle,
QLabel#appVersion,
QLabel#statusText,
QLabel#statusMeta,
QLabel#pipelineMetaLabel,
QLabel#searchMatchesLabel,
QLabel#listTileMeta,
QLabel#stageInspectorStatus,
QLabel#stageInspectorMeta {
  color: #94A3B8;
}

QLabel#pipelineActivityPrimary {
  color: #E2E8F0;
}

QPushButton,
QToolButton#audioControlButton,
QToolButton#pipelineTileActionButton {
  background: #111827;
  color: #E2E8F0;
  border-color: #334155;
}

QPushButton:hover,
QToolButton#audioControlButton:hover,
QToolButton#pipelineTileActionButton:hover {
  background: #1F2937;
}

QPushButton:disabled {
  color: #64748B;
  background: rgba(17, 24, 39, 170);
  border-color: #334155;
}

QToolButton#pipelineTileActionButton {
  background: #0B1220;
  color: #E2E8F0;
  border: 1px solid #334155;
}

QToolButton#pipelineTileActionButton:hover {
  background: #1F2937;
  border-color: #475569;
}

QToolButton#pipelineTileActionButton:disabled {
  color: #64748B;
  background: #111827;
  border: 1px solid #334155;
}

QLabel#pipelineTileStatusBadge[state="idle"],
QLabel#pipelineTileStatusBadge[state="disabled"] {
  color: #AEBBD0;
  background: #202938;
  border: 1px solid #3A4C61;
}

QLabel#pipelineTileStatusBadge[state="ready"],
QLabel#pipelineTileStatusBadge[state="running"] {
  color: #B7CCE6;
  background: #223349;
  border: 1px solid #4D6887;
}

QLabel#pipelineTileStatusBadge[state="completed"] {
  color: #B9DDCB;
  background: #22372F;
  border: 1px solid #4D7366;
}

QLabel#pipelineTileStatusBadge[state="skipped"] {
  color: #DFCFAE;
  background: #3A3022;
  border: 1px solid #67573F;
}

QLabel#pipelineTileStatusBadge[state="failed"] {
  color: #E0BAC6;
  background: #3A252C;
  border: 1px solid #6A4450;
}

QLabel#pipelineTileProgressBadge {
  color: #B7CCE6;
  background: #223349;
  border: 1px solid #4D6887;
}

QLabel#pipelineTileProgressBadge[state="idle"],
QLabel#pipelineTileProgressBadge[state="disabled"] {
  color: #AEBBD0;
  background: #202938;
  border: 1px solid #3A4C61;
}

QLabel#pipelineTileProgressBadge[state="completed"] {
  color: #B9DDCB;
  background: #22372F;
  border: 1px solid #4D7366;
}

QLabel#pipelineTileProgressBadge[state="failed"] {
  color: #E0BAC6;
  background: #3A252C;
  border: 1px solid #6A4450;
}

QPushButton#pipelineRunButton {
  background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #2563EB, stop:0.5 #0EA5E9, stop:1 #14B8A6);
}

QPushButton#pipelineRunButton:hover {
  background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #1D4ED8, stop:0.5 #0284C7, stop:1 #0F766E);
}

QTabWidget::pane {
  background: #0B1220;
  border-color: #334155;
}

QTabBar::tab {
  background: #0F172A;
  color: #94A3B8;
}

QTabBar::tab:selected {
  color: #F8FAFC;
  border-bottom: 2px solid #38BDF8;
}

QProgressBar {
  background: #0B1220;
  border-color: #334155;
}

QProgressBar::chunk {
  background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #2563EB, stop:0.5 #0EA5E9, stop:1 #14B8A6);
}

QCheckBox::indicator:unchecked {
  background: #0B1220;
  border-color: #64748B;
}

QCheckBox::indicator:checked {
  background: #38BDF8;
  border-color: #38BDF8;
}

/* Shared semi-transparent surface scale for dark theme */
QFrame[card="true"],
QFrame#appHeader,
QFrame#stdPanel,
QFrame#stdCard,
QFrame#pipelineTileV2,
QFrame#stageSettingsDrawer,
QFrame#historyItemCard,
QFrame#stageTile,
QFrame#modelCard,
QFrame#stageInspectorHeader,
QFrame#audioControlBar,
QFrame#listTileCard,
QFrame#pipelineActivityTile,
QGroupBox {
  background: rgba(15, 23, 42, 190);
  border-color: #334155;
}

QLineEdit,
QTextEdit,
QComboBox,
QListWidget,
QTextBrowser#stdTextSourceView,
QComboBox QAbstractItemView {
  background: rgba(11, 18, 32, 208);
  border-color: #334155;
}

QPushButton,
QToolButton#audioControlButton,
QToolButton#pipelineTileActionButton,
QToolButton#stdActionButton {
  background: rgba(15, 23, 42, 172);
  border-color: #334155;
}

QPushButton:hover,
QToolButton#audioControlButton:hover,
QToolButton#pipelineTileActionButton:hover,
QToolButton#stdActionButton:hover {
  background: rgba(30, 41, 59, 186);
}

QPushButton:disabled {
  background: rgba(15, 23, 42, 128);
  border-color: #334155;
}

QTabBar::tab,
QTabBar#artifactKindTabBar::tab,
QListWidget#artifactsKindList::item {
  background: rgba(15, 23, 42, 170);
  border-color: #334155;
}

QToolButton#historyItemRename {
  background: rgba(67, 56, 202, 140);
  border-color: #6366F1;
}

QToolButton#historyItemRerun {
  background: rgba(30, 58, 138, 150);
  border-color: #3B82F6;
}

QToolButton#historyItemDelete {
  background: rgba(127, 29, 29, 150);
  border-color: #EF4444;
}
""",
    "light_mono": """
QPushButton#pipelineRunButton {
  background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #64748B, stop:1 #94A3B8);
}

QPushButton#pipelineRunButton:hover {
  background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #475569, stop:1 #64748B);
}

QLabel#statusBrand {
  color: #475569;
}

QTabBar::tab:selected {
  border-bottom: 2px solid #64748B;
}

QListWidget::item:selected,
QTabBar#artifactKindTabBar::tab:selected {
  background: rgba(100, 116, 139, 28);
  color: #334155;
  border-color: #94A3B8;
}

QCheckBox::indicator:checked {
  border-color: #64748B;
  background: #64748B;
}
QLabel#pipelineTileStatusBadge[state="ready"],
QLabel#pipelineTileStatusBadge[state="running"],
QLabel#pipelineTileStatusBadge[state="completed"],
QLabel#pipelineTileStatusBadge[state="skipped"],
QLabel#pipelineTileStatusBadge[state="failed"],
QLabel#pipelineTileProgressBadge,
QLabel#pipelineTileProgressBadge[state="completed"],
QLabel#pipelineTileProgressBadge[state="failed"] {
  color: #334155;
  background: rgba(100, 116, 139, 26);
  border: 1px solid #94A3B8;
}

QLabel#stdBadge[kind="focus"],
QLabel#stdBadge[kind="related"],
QLabel#stdBadge[kind="success"],
QLabel#stdBadge[kind="warning"],
QLabel#stdBadge[kind="danger"] {
  color: #334155;
  background: rgba(100, 116, 139, 24);
  border: 1px solid #94A3B8;
}

QToolButton#historyItemRename,
QToolButton#historyItemRerun,
QToolButton#historyItemDelete {
  color: #334155;
  background: rgba(100, 116, 139, 22);
  border: 1px solid #CBD5E1;
}
""",
    "dark_mono": """
QLabel#statusBrand {
  color: #94A3B8;
}

QPushButton#pipelineRunButton {
  background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #64748B, stop:1 #94A3B8);
}

QPushButton#pipelineRunButton:hover {
  background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #475569, stop:1 #64748B);
}

QTabBar::tab:selected {
  color: #E2E8F0;
  border-bottom: 2px solid #94A3B8;
}

QListWidget::item:selected,
QTabBar#artifactKindTabBar::tab:selected {
  color: #E2E8F0;
  background: rgba(100, 116, 139, 34);
  border-color: #94A3B8;
}

QLabel#pipelineTileStatusBadge[state="ready"],
QLabel#pipelineTileStatusBadge[state="running"],
QLabel#pipelineTileStatusBadge[state="completed"],
QLabel#pipelineTileStatusBadge[state="skipped"],
QLabel#pipelineTileStatusBadge[state="failed"],
QLabel#pipelineTileProgressBadge,
QLabel#pipelineTileProgressBadge[state="completed"],
QLabel#pipelineTileProgressBadge[state="failed"] {
  color: #E2E8F0;
  background: rgba(71, 85, 105, 170);
  border: 1px solid #94A3B8;
}

QLabel#stdBadge[kind="focus"],
QLabel#stdBadge[kind="related"],
QLabel#stdBadge[kind="success"],
QLabel#stdBadge[kind="warning"],
QLabel#stdBadge[kind="danger"] {
  color: #E2E8F0;
  background: rgba(71, 85, 105, 160);
  border: 1px solid #94A3B8;
}

QToolButton#historyItemRename,
QToolButton#historyItemRerun,
QToolButton#historyItemDelete {
  color: #E2E8F0;
  background: rgba(71, 85, 105, 150);
  border: 1px solid #64748B;
}

QFrame#historyItemCard[selected="true"] QToolButton#historyItemRename,
QFrame#historyItemCard[selected=true] QToolButton#historyItemRename,
QFrame#historyItemCard[selected="true"] QToolButton#historyItemRerun,
QFrame#historyItemCard[selected=true] QToolButton#historyItemRerun,
QFrame#historyItemCard[selected="true"] QToolButton#historyItemDelete,
QFrame#historyItemCard[selected=true] QToolButton#historyItemDelete {
  background: rgba(100, 116, 139, 168);
  border: 1px solid #94A3B8;
}

QCheckBox::indicator:checked {
  background: #94A3B8;
  border-color: #94A3B8;
}
""",
}


_THEME_ID_ALIASES = {
    "light_emerald": "light_mono",
    "light_sunset": "light_mono",
    "mono_light": "light_mono",
    "monochrome_light": "light_mono",
    "mono_dark": "dark_mono",
    "monochrome_dark": "dark_mono",
}


def normalize_theme_id(theme_id: str) -> str:
    tid = str(theme_id or "").strip().lower()
    tid = _THEME_ID_ALIASES.get(tid, tid)
    return tid if tid in THEME_IDS else DEFAULT_THEME_ID


def build_app_stylesheet(theme_id: str) -> str:
    tid = normalize_theme_id(theme_id)
    if tid == DEFAULT_THEME_ID:
        return APP_STYLESHEET
    if tid == "dark_mono":
        return (
            APP_STYLESHEET
            + "\n"
            + str(_THEME_OVERRIDES.get("dark", ""))
            + "\n"
            + str(_THEME_OVERRIDES.get("dark_mono", ""))
        )
    return APP_STYLESHEET + "\n" + str(_THEME_OVERRIDES.get(tid, ""))

"""Shared CSS/layout constants for the modular settings TUI."""

SETTINGS_SCREEN_CSS = """
Screen {
    align: left top;
}
#settings_root {
    width: 100%;
    height: 1fr;
    padding: 0 2 1 2;
}
#settings_tabs {
    padding-top: 1;
    height: 1fr;
}
TabPane {
    padding: 0;
    height: 1fr;
}
.settings_page {
    width: 1fr;
    height: 1fr;
}
.settings_scroll {
    width: 1fr;
    height: 1fr;
    padding: 1 1 0 1;
}
.settings_form {
    width: 1fr;
    height: auto;
}
.settings_field_group {
    height: auto;
    margin-bottom: 1;
}
.settings_field_group Label {
    margin-bottom: 1;
}
.settings_toggle_row {
    align: left middle;
    height: auto;
}
.settings_toggle_row Switch {
    margin: 0;
}
.settings_side_label {
    height: auto;
    align: left middle;
}
.settings_side_label Label {
    margin: 0;
    padding-top: 1;
    width: auto;
    text-align: left;
    content-align: left middle;
}
.settings_toggle_row .settings_side_label {
    width: 1fr;
    margin-left: 1;
}
.settings_toggle_row .settings_side_label Label {
    width: 100%;
}
.settings_action_row {
    height: auto;
    align: center middle;
    padding: 1 1 0 1;
}
.settings_action_row Button {
    margin: 0 1;
    min-width: 18;
}
#settings_footer_row {
    height: auto;
    align: center middle;
    padding-top: 1;
}
#settings_footer_row Button {
    min-width: 20;
}
Input, Select, TextArea {
    width: 100%;
}
#character_selector_row {
    height: auto;
    align: center middle;
    padding-bottom: 1;
}
#character_selector_row .settings_side_label {
    width: auto;
    margin-right: 1;
}
#character_selector_row .settings_side_label Label {
    width: auto;
    text-style: bold;
}
#character_pick {
    width: 44;
    max-width: 100%;
}
#character_fields_row {
    height: auto;
    margin-bottom: 1;
}
.settings_column {
    width: 1fr;
    height: auto;
    margin: 0 1;
}
#stt_v1_fields, #stt_v2_fields {
    width: 1fr;
    height: auto;
}
#character_instruction_group {
    height: auto;
    min-height: 12;
}
#character_instructions {
    height: 12;
    min-height: 8;
}
"""

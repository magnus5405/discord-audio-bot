"""Shared CSS/layout constants for the modular settings TUI."""

SETTINGS_SCREEN_CSS = """
Screen {
    align: left top;
}
#settings_root {
    width: 100%;
    height: 1fr;
    min-height: 0;
    padding: 0 2 1 2;
}
#settings_tabs {
    padding-top: 1;
    height: 1fr;
    min-height: 0;
}
TabPane {
    padding: 0;
    height: 1fr;
    min-height: 0;
}
.settings_page {
    width: 1fr;
    height: 1fr;
    min-height: 0;
}
.settings_scroll {
    width: 1fr;
    height: 1fr;
    min-height: 0;
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
.character_aliases_list {
    width: 1fr;
    height: auto;
}
#character_alias_header_row {
    height: auto;
    width: 1fr;
    align: left top;
    margin-top: 1;
    margin-bottom: 1;
}
#character_alias_header_row .settings_column {
    width: 1fr;
    height: auto;
}
.character_alias_header_left Label {
    margin-bottom: 0;
    text-align: left;
    text-style: bold;
}
#character_alias_section_title {
    padding-top: 1;
}
.character_alias_header_right {
    align: right middle;
    height: auto;
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
/* Alias rows: global Input width 100% would hide the Delete button in the Horizontal row. */
CharacterAliasRow Input.character_alias_input {
    width: 1fr;
    min-width: 8;
}
CharacterAliasRow Button.btn_remove_alias {
    width: auto;
    min-width: 10;
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
    min-height: 14;
}
#character_instructions {
    height: 14;
    min-height: 10;
}
"""

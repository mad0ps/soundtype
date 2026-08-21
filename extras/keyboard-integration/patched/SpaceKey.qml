/*
 * Copyright 2013 Canonical Ltd.
 *
 * This program is free software; you can redistribute it and/or modify
 * it under the terms of the GNU Lesser General Public License as published by
 * the Free Software Foundation; version 3.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU Lesser General Public License for more details.
 *
 * You should have received a copy of the GNU Lesser General Public License
 * along with this program.  If not, see <http://www.gnu.org/licenses/>.
 */

import QtQuick 2.4
import Lomiri.Components 1.3

import "key_constants.js" as UI
import "languages.js" as Languages

ActionKey {
    label: " ";
    shifted: " ";

    normalColor: fullScreenItem.theme.charKeyColor
    pressedColor: fullScreenItem.theme.charKeyPressedColor

    action: "space"
    switchBackFromSymbols: true

    overridePressArea: true

    Label {
        id: langLabel
        anchors.centerIn: parent
        anchors.verticalCenterOffset: -parent.rowMargin / 2 - units.gu(0.15)
        font.family: UI.fontFamily
        font.weight: Font.Light
        font.pixelSize: parent.fontSize * 0.6
        text: Languages.languageIdToName(maliit_input_method.activeLanguage)
        horizontalAlignment: Text.AlignHCenter
        visible: !panel.hideKeyLabels
        // на время диктовки пробел отдан волне
        opacity: spaceWave.visible ? 0.12 : UI.spaceOpacity
    }

    // SoundType: индикатор диктовки в левой части пробела (справа его
    // закрывает палец при холде); серый = движок не в памяти, зелёный =
    // готов (движок загружен), красный пульс = запись, жёлтый = занят
    // (загрузка движка или расшифровка)
    Icon {
        id: micIndicator
        name: "audio-input-microphone-symbolic"
        width: units.gu(2.6)
        height: width
        anchors.verticalCenter: langLabel.verticalCenter
        anchors.left: parent.left
        anchors.leftMargin: units.gu(1)
        visible: !panel.hideKeyLabels
        color: fullScreenItem.dictationStatus === "recording" ? "red"
             : fullScreenItem.dictationStatus === "processing" ? "gold"
             : fullScreenItem.dictationStatus === "ready" ? "limegreen"
             : "gray"
        opacity: 0.9
    }

    // SoundType: стационарный эквалайзер — бары НЕ движутся по горизонтали,
    // каждый стоит на месте и дышит от громкости (общая огибающая) со своим
    // коэффициентом и лёгким собственным колыханием, чтобы ряд не был
    // синхронным. В тишине — ряд кружочков.
    Row {
        id: spaceWave
        spacing: units.gu(0.7)
        anchors.verticalCenter: micIndicator.verticalCenter
        anchors.left: micIndicator.right
        anchors.leftMargin: units.gu(0.8)
        anchors.right: parent.right
        anchors.rightMargin: units.gu(1)
        visible: micIndicator.visible
                 && (fullScreenItem.dictationStatus === "recording"
                     || fullScreenItem.dictationStatus === "processing")
        property real barW: units.gu(0.45)
        property int bars: Math.max(6, Math.floor((width + spacing) / (barW + spacing)))

        Repeater {
            model: spaceWave.bars
            delegate: Item {
                width: spaceWave.barW
                height: units.gu(2.2)

                // статичный «характер» бара + собственное медленное колыхание
                property real gain: 0.55 + 0.45 * Math.abs(Math.sin((index + 1) * 2.399))
                property real sway: 0.0

                SequentialAnimation on sway {
                    running: spaceWave.visible && !fullScreenItem.dictationMicSilent
                    loops: Animation.Infinite
                    NumberAnimation {
                        from: 0.0; to: 1.0
                        duration: 240 + (index * 83) % 170
                        easing.type: Easing.InOutSine
                    }
                    NumberAnimation {
                        from: 1.0; to: 0.0
                        duration: 240 + (index * 83) % 170
                        easing.type: Easing.InOutSine
                    }
                }

                Rectangle {
                    anchors.centerIn: parent
                    width: parent.width
                    radius: width / 2
                    antialiasing: true
                    color: fullScreenItem.dictationMicSilent ? "gray"
                         : fullScreenItem.dictationStatus === "processing" ? "gold"
                         : "red"
                    height: Math.max(parent.width,
                                     parent.height * Math.min(1.0,
                                         fullScreenItem.dictationEnvelope
                                         * gain * (0.6 + 0.4 * sway)))
                    Behavior on height {
                        NumberAnimation { duration: 130; easing.type: Easing.OutCubic }
                    }
                }
            }
        }
    }

    MouseArea {
        id: swipeArea
        anchors.fill: parent

        // SoundType hold-space: после pressAndHold решение откладывается —
        // движение пальца = тачпад (как в стоке), отпускание без движения =
        // toggle диктовки.
        property bool holdArmed: false
        property real holdX: 0
        property real holdY: 0

        function enterCursorSwipe(mx, my) {
            holdArmed = false
            fullScreenItem.prevSwipePositionX = mx
            fullScreenItem.prevSwipePositionY = my
            fullScreenItem.cursorSwipe = true
            spaceKey.currentlyPressed = false
        }

        onPressAndHold: {
            holdArmed = true
            holdX = mouseX
            holdY = mouseY
            fullScreenItem.dictationHoldFeedback()
        }

        onPressed: {
            fullScreenItem.keyFeedback();
            spaceKey.currentlyPressed = true
            fullScreenItem.timerSwipe.stop()
        }
        onReleased: {
            if (holdArmed) {
                holdArmed = false
                spaceKey.currentlyPressed = false
                fullScreenItem.toggleDictation()
                return
            }
            if (fullScreenItem.cursorSwipe) {
                fullScreenItem.timerSwipe.restart()
            } else if (fullScreenItem.dictationStatus === "recording") {
                // короткий тап во время записи = стоп диктовки, пробел не печатаем
                spaceKey.currentlyPressed = false
                fullScreenItem.toggleDictation()
            } else {
                spaceKey.currentlyPressed = false
                event_handler.onKeyReleased("", "space")
                if (switchBackFromSymbols && panel.state === "SYMBOLS") {
                    panel.state = "CHARACTERS"
                }
            }
        }

        onMouseXChanged: {
            if (holdArmed && (Math.abs(mouseX - holdX) > units.gu(1) || Math.abs(mouseY - holdY) > units.gu(1))) {
                enterCursorSwipe(mouseX, mouseY)
            }
            if (fullScreenItem.cursorSwipe) {
                fullScreenItem.processSwipe(mouseX, mouseY);
            }
        }

        onMouseYChanged: {
            if (holdArmed && (Math.abs(mouseX - holdX) > units.gu(1) || Math.abs(mouseY - holdY) > units.gu(1))) {
                enterCursorSwipe(mouseX, mouseY)
            }
            if (fullScreenItem.cursorSwipe) {
                fullScreenItem.processSwipe(mouseX, mouseY);
            }
        }
    }

}

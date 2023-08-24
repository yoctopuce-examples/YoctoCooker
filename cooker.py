#!/usr/bin/python
# -*- coding: utf-8 -*-
import os, sys
import math

from yocto_api import *
from yocto_display import *
from yocto_anbutton import *
from yocto_temperature import *
from yocto_quadraturedecoder import *

YOCTOHUB_IP_ADDRESS = "192.168.x.x" # set the address here

class DisplayGraph:
    def __init__(self, disp, destLayer, offlineLayer):
        self.disp = disp
        self.buffer = None
        self.width = 0
        self.height = 0
        self.offlineIdx = offlineLayer
        self.visibleIdx = destLayer
        self.sensor = None
        self.clearGraph()

    def clearGraph(self):
        if self.sensor is not None:
            self.sensor.registerTimedReportCallback(None)
        self.sensor = None
        self.zoom = 1
        self.measures = []
        self.updateDisplay()

    def setSensor(self, sensor, frequency):
        self.sensor = sensor
        self.measures = []
        if sensor.isOnline():
            sensor.set_reportFrequency(frequency)
            sensor.registerTimedReportCallback(self.addMeasure)

    def changeZoom(self, deltaRot):
        self.zoom *= pow(2, deltaRot)

    def addMeasure(self, sensor, measure):
        self.measures.append(measure)
        self.updateDisplay()

    def updateDisplay(self):
        if not self.disp.isOnline():
            return
        if self.buffer is None:
            self.buffer = disp.get_displayLayer(self.offlineIdx)
            self.width = disp.get_displayWidth()
            self.height = disp.get_displayHeight()
        self.buffer.hide()
        self.buffer.clear()
        if len(self.measures) == 0:
            self.disp.swapLayerContent(self.offlineIdx, self.visibleIdx)
            return
        # determine display range based on desired zoom level
        xmargin = 18
        ymargin = 10
        endIdx = len(self.measures)
        startIdx = endIdx - int(round((self.width - xmargin) / self.zoom))
        if startIdx < 0: startIdx = 0
        # summarize data based on desired zoom level
        start = self.measures[startIdx].get_startTimeUTC()
        stop = self.measures[endIdx-1].get_endTimeUTC()
        deltaSec = 60 * (int((stop - start) / 240) + 1)
        nextMin = datetime.datetime.fromtimestamp(int(start / deltaSec + 1) * deltaSec)
        labels = []
        values = []
        sum = 0
        nval = 0
        frac = 0
        for idx in range(startIdx, endIdx):
            if nval == 0:
                start = self.measures[idx].get_startTimeUTC_asDatetime()
            sum += self.measures[idx].get_averageValue()
            nval += 1
            frac += self.zoom
            if frac >= 1:
                values.append(sum / nval)
                stop = self.measures[idx].get_endTimeUTC_asDatetime()
                if start < nextMin and stop >= nextMin:
                    labels.append('{0}:{1:02d}'.format(nextMin.hour, nextMin.minute))
                    nextMin += datetime.timedelta(seconds=deltaSec)
                else:
                    labels.append('')
                sum = 0
                nval = 0
                frac = 0
        if nval > 0:
            values.append(sum / nval)
            labels.append('')
        # compute scaling factor based on min/max
        minVal = math.floor(min(values)-1)
        delta = round((max(values) + 3 - minVal) / 2) * 2
        maxVal = minVal + delta
        disph = self.height - ymargin
        yscale = - disph / delta
        yofs = disph / 2 - yscale * (maxVal + minVal) / 2
        # draw graph from right to left
        minY = self.height-ymargin
        medY = minY // 2
        xpos = self.width - 1
        idx = len(values) - 1
        lastVal = round(values[idx],1)
        ypos = round(yofs + yscale * values[idx])
        tpos = medY//2 if ypos > medY else (3*medY)//2
        self.buffer.selectGrayPen(255)
        self.buffer.drawText(xpos, tpos, YDisplayLayer.ALIGN.CENTER_RIGHT, str(lastVal) + '°')
        self.buffer.moveTo(xpos, ypos)
        if idx == 0: self.buffer.lineTo(xpos-2, ypos)
        while xpos > 0 and idx > 0:
            idx -= 1
            xpos -= 1 if self.zoom < 1.5 else round(self.zoom)
            self.buffer.lineTo(xpos, round(yofs + yscale * values[idx]))
        # draw axis, including Y labels
        self.buffer.moveTo(xmargin, 0)
        self.buffer.lineTo(xmargin, minY)
        self.buffer.lineTo(self.width, minY)
        self.buffer.moveTo(xmargin-1, 0)
        self.buffer.lineTo(xmargin+1, 0)
        self.buffer.drawText(xmargin-1, 0, YDisplayLayer.ALIGN.TOP_RIGHT, str(maxVal)+'°')
        self.buffer.moveTo(xmargin-1, medY)
        self.buffer.lineTo(xmargin+1, medY)
        self.buffer.drawText(xmargin-1, medY, YDisplayLayer.ALIGN.CENTER_RIGHT, str(int((minVal+maxVal)/2))+'°')
        self.buffer.drawText(xmargin-1, minY, YDisplayLayer.ALIGN.BASELINE_RIGHT, str(minVal)+'°')
        # draw x axis labels
        idx = len(labels) - 1
        xpos = self.width - 1
        while xpos > 0 and idx > 0:
            if labels[idx] != '':
                self.buffer.moveTo(xpos, minY-1)
                self.buffer.lineTo(xpos, minY+1)
                self.buffer.drawText(xpos, minY+3, YDisplayLayer.ALIGN.TOP_CENTER, labels[idx])
            idx -= 1
            xpos -= 1 if self.zoom < 1.5 else round(self.zoom)
        # push to display
        self.disp.swapLayerContent(self.offlineIdx, self.visibleIdx)

class DisplayMenu:
    def __init__(self, disp, destLayer, offlineLayer, rotaryEncoder, pushButton, menu):
        self.disp = disp
        self.buffer = None
        self.width = 0
        self.height = 0
        self.offlineIdx = offlineLayer
        self.visibleIdx = destLayer
        self.rotary = rotaryEncoder
        self.push = pushButton
        self.menu = menu
        self.currMenu = None
        self.defRotCb = None
        self.lastClick = YAPI.GetTickCount()
        self.lastRot = 0
        self.position = []
        pushButton.registerValueCallback(self.pushCb)
        rotaryEncoder.registerValueCallback(self.rotateCb)

    def setDefaultRotaryCallback(self, defaultCallback):
        self.defRotCb = defaultCallback

    def pushCb(self, anButton, valueStr):
        if valueStr == '0':
            return
        # debounce: ignore any click event below one second after previous
        if (YAPI.GetTickCount() - self.lastClick).total_seconds() < 1:
            return
        self.lastClick = YAPI.GetTickCount()
        if len(self.position) > 0 and self.position[-1] == 0:
            del self.position[-1]
        else:
            self.position.append(0)
        self.currMenu = None
        if len(self.position) > 0:
            self.currMenu = self.menu
            depth = 0
            while depth < len(self.position)-1:
                self.currMenu = self.currMenu[self.position[depth]]
                depth += 1
            if hasattr(self.currMenu[1], '__call__'):
                # invoke selected function
                action = self.currMenu[1]
                action()
                # close menu after action
                self.position = []
                self.currMenu = None
        self.updateDisplay(True)

    def rotateCb(self, anButton, valueStr):
        newRot = int(valueStr)
        delta = newRot - self.lastRot
        self.lastRot = newRot
        if len(self.position) == 0:
            if(self.defRotCb is not None):
                self.defRotCb(delta)
            return
        newIdx = max(self.position[-1] + delta, 0)
        newIdx = min(newIdx, len(self.currMenu)-1)
        self.position[-1] = newIdx
        self.updateDisplay(False)

    def updateDisplay(self, isClick):
        if not self.disp.isOnline():
            return
        if self.buffer is None:
            self.buffer = disp.get_displayLayer(self.offlineIdx)
            self.width = disp.get_displayWidth()
            self.height = disp.get_displayHeight()
        menuWidth = 48
        lineHeight = 10
        if(self.currMenu is None):
            # scroll out menu
            menuLayer = self.disp.get_displayLayer(self.visibleIdx)
            menuLayer.setLayerPosition(menuWidth, 0, 200)
            return
        labels = []
        for item in self.currMenu:
            labels.append(item[0])
        if(len(self.position) > 1):
            # submenu, set first label to "back"
            labels[0] = '(back)'
        elif isClick:
            # main menu, schedule menu scroll-in
            menuLayer = self.disp.get_displayLayer(self.visibleIdx)
            menuLayer.setLayerPosition(menuWidth, 0, 0)
            menuLayer.setLayerPosition(0, 0, 200)
        selIdx = self.position[-1]
        self.buffer.hide()
        self.buffer.clear()
        self.buffer.selectGrayPen(0)
        self.buffer.drawBar(self.width, 0, self.width - menuWidth, len(labels) * lineHeight)
        self.buffer.selectGrayPen(255)
        self.buffer.drawRect(self.width, 0, self.width - menuWidth, len(labels) * lineHeight)
        for i in range(0, len(labels)):
            if i != selIdx:
                self.buffer.drawText(self.width - menuWidth + 4, (i+0.5) * lineHeight,
                                     YDisplayLayer.ALIGN.CENTER_LEFT, labels[i])
        self.buffer.drawBar(self.width, selIdx * lineHeight,
                            self.width - menuWidth, (selIdx+1) * lineHeight - 1)
        self.buffer.selectGrayPen(0)
        self.buffer.drawText(self.width - menuWidth + 4, (selIdx+0.5) * lineHeight,
                             YDisplayLayer.ALIGN.CENTER_LEFT, labels[selIdx])
        disp.swapLayerContent(self.offlineIdx, self.visibleIdx)

def log(msg):
    print("*** ", msg)

def arrival(module):
    log("device arrival: "+module.get_serialNumber())

def removal(module):
    log("device removal: "+module.get_serialNumber())

# Setup the API to use local USB devices
errmsg = YRefParam
if YAPI.PreregisterHub(YOCTOHUB_IP_ADDRESS, errmsg) != YAPI.SUCCESS:
    sys.exit("init error: " + str(errmsg))
print("Waiting for Yoctopuce devices to be detected...")
YAPI.RegisterDeviceArrivalCallback(arrival)
YAPI.RegisterDeviceRemovalCallback(removal)

#YAPI.DisableExceptions()

disp = YDisplay.FindDisplay("cookingDisplay")
but1 = YAnButton.FindAnButton('but1')
but2 = YAnButton.FindAnButton('but2')
push = YAnButton.FindAnButton('rotaryPush')
rotary = YQuadratureDecoder.FindQuadratureDecoder('rotary')
cookingTemp = YTemperature.FindTemperature('cookingTemp')

# setup grapher on Layer 1, Menu on layer 2 and double-buffer on layer 3
grapher = DisplayGraph(disp, 1, 3)
menu = DisplayMenu(disp, 2, 3, rotary, push, [
    ['Exit'],
    ['Start',
        ['6/min', lambda: grapher.setSensor(cookingTemp, "6/m") ],
        ['20/min', lambda: grapher.setSensor(cookingTemp, "20/m")],
        ['60/min', lambda: grapher.setSensor(cookingTemp, "60/m")],
        ['2/sec', lambda: grapher.setSensor(cookingTemp, "2/s")]
     ],
    ['Clear', lambda: grapher.clearGraph() ],
])
menu.setDefaultRotaryCallback(grapher.changeZoom)

# This software runs event-based to handle hot-plug
while True:
    YAPI.UpdateDeviceList()
    YAPI.Sleep(1000)

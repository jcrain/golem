import logging
import os
import random
import math
import shutil

from collections import OrderedDict

from TaskState import RendererDefaults, RendererInfo
from GNRTask import GNROptions
from RenderingTask import RenderingTask, RenderingTaskBuilder
from RenderingDirManager import getTestTaskPath, getTmpPath

from RenderingTaskCollector import exr_to_pil, RenderingTaskCollector
from examples.gnr.RenderingEnvironment import VRayEnvironment
from examples.gnr.ui.VRayDialog import VRayDialog
from examples.gnr.customizers.VRayDialogCustomizer import VRayDialogCustomizer

from PIL import Image

logger = logging.getLogger(__name__)

##############################################
def buildVRayRendererInfo():
    defaults = RendererDefaults()
    defaults.outputFormat = "EXR"
    defaults.mainProgramFile = os.path.normpath( os.path.join( os.environ.get('GOLEM'), 'examples\\tasks\\VRayTask.py' ) )
    defaults.minSubtasks = 1
    defaults.maxSubtasks = 100
    defaults.defaultSubtasks = 6

    renderer = RendererInfo( "VRay", defaults, VRayTaskBuilder, VRayDialog, VRayDialogCustomizer, VRayRendererOptions )
    renderer.outputFormats = [ "BMP", "EPS", "EXR", "GIF", "IM", "JPEG", "PCX", "PDF", "PNG", "PPM", "TIFF" ]
    renderer.sceneFileExt = [ "vrscene" ]

    return renderer

##############################################
class VRayRendererOptions( GNROptions ):

    #######################
    def __init__( self ):
        self.environment = VRayEnvironment()
        self.rtEngine = 0
        self.rtEngineValues = {0: 'No engine', 1: 'CPU', 3: 'OpenGL', 5: 'CUDA' }
        self.useFrames = False
        self.frames = range(1, 11)

##############################################
class VRayTaskBuilder( RenderingTaskBuilder ):
    #######################
    def build( self ):
        mainSceneDir = os.path.dirname( self.taskDefinition.mainSceneFile )

        vRayTask = VRayTask(       self.clientId,
                                   self.taskDefinition.taskId,
                                   mainSceneDir,
                                   self.taskDefinition.mainSceneFile,
                                   self.taskDefinition.mainProgramFile,
                                   self._calculateTotal( buildVRayRendererInfo(), self.taskDefinition ),
                                   self.taskDefinition.resolution[0],
                                   self.taskDefinition.resolution[1],
                                   os.path.splitext( os.path.basename( self.taskDefinition.outputFile ) )[0],
                                   self.taskDefinition.outputFile,
                                   self.taskDefinition.outputFormat,
                                   self.taskDefinition.fullTaskTimeout,
                                   self.taskDefinition.subtaskTimeout,
                                   self.taskDefinition.resources,
                                   self.taskDefinition.estimatedMemory,
                                   self.rootPath,
                                   self.taskDefinition.rendererOptions.rtEngine,
                                   self.taskDefinition.rendererOptions.useFrames,
                                   self.taskDefinition.rendererOptions.frames
                                   )
        return vRayTask

    #######################
    def _calculateTotal(self, renderer, definition ):
        if definition.optimizeTotal:
            if self.taskDefinition.rendererOptions.useFrames:
                return len( self.taskDefinition.rendererOptions.frames )
            else:
                return renderer.defaults.defaultSubtasks

        if self.taskDefinition.rendererOptions.useFrames:
            numFrames = len( self.taskDefinition.rendererOptions.frames )
            if definition.totalSubtasks > numFrames:
                est = int( math.floor( float( definition.totalSubtasks ) / float( numFrames ) ) ) * numFrames
                if est != definition.totalSubtasks:
                    logger.warning("Too many subtasks for this task. {} subtasks will be used".format( numFrames ) )
                return est

            est = int ( math.ceil( float( numFrames ) / float( math.ceil( float( numFrames ) / float( definition.totalSubtasks ) ) ) ) )
            if est != definition.totalSubtasks:
                logger.warning("Too many subtasks for this task. {} subtasks will be used.".format( est ) )

            return est

        if renderer.defaults.minSubtasks <= definition.totalSubtasks <= renderer.defaults.maxSubtasks:
            return definition.totalSubtasks
        else :
            return renderer.defaults.defaultSubtasks

##############################################
class VRayTask( RenderingTask ):
    #######################
    def __init__( self,
                  clientId,
                  taskId,
                  mainSceneDir,
                  mainSceneFile,
                  mainProgramFile,
                  totalTasks,
                  resX,
                  resY,
                  outfilebasename,
                  outputFile,
                  outputFormat,
                  fullTaskTimeout,
                  subtaskTimeout,
                  taskResources,
                  estimatedMemory,
                  rootPath,
                  rtEngine,
                  useFrames,
                  frames,
                  returnAddress = "",
                  returnPort = 0):

        RenderingTask.__init__( self, clientId, taskId, returnAddress, returnPort,
                          VRayEnvironment.getId(), fullTaskTimeout, subtaskTimeout,
                          mainProgramFile, taskResources, mainSceneDir, mainSceneFile,
                          totalTasks, resX, resY, outfilebasename, outputFile, outputFormat,
                          rootPath, estimatedMemory )

        self.rtEngine = rtEngine
        self.collectedAlphaFiles = {}

        self.useFrames = useFrames
        self.frames = frames
        self.framesGiven = {}

        if useFrames:
            self.previewFilePath = [ None ] * len ( frames )
            if len( frames ) > self.totalTasks:
                for task in range(1, self.totalTasks + 1):
                    self.collectedFileNames[ task ] = []

    #######################
    def restart( self ):
        RenderingTask.restart( self )
        self.previewPartsFilePath = None
        if self.useFrames:
            self.previewFilePath = [ None ] * len( self.frames )

    #######################
    def queryExtraData( self, perfIndex, numCores = 0 ):

        startTask, endTask = self._getNextTask()

        workingDirectory = self._getWorkingDirectory()
        sceneFile = self._getSceneFileRelPath()

        if self.useFrames:
            frames, parts = self.__chooseFrames( self.frames, startTask, self.totalTasks )
        else:
            frames = []
            parts = 1

        extraData =          {      "pathRoot" : self.mainSceneDir,
                                    "startTask" : startTask,
                                    "endTask" : endTask,
                                    "totalTasks" : self.totalTasks,
                                    "outfilebasename" : self.outfilebasename,
                                    "sceneFile" : sceneFile,
                                    "width" : self.resX,
                                    "height": self.resY,
                                    "rtEngine": self.rtEngine,
                                    "useFrames": self.useFrames,
                                    "frames": frames,
                                    "parts": parts
                                }


        hash = "{}".format( random.getrandbits(128) )
        self.subTasksGiven[ hash ] = extraData
        self.subTasksGiven[ hash ][ 'status' ] = 'sent'
        if parts != 1 and frames[0] not in self.framesGiven:
            self.framesGiven[ frames[0] ] = {}

        if not self.useFrames:
            self._updateTaskPreview()
        return self._newComputeTaskDef( hash, extraData, workingDirectory, perfIndex )

    #######################
    def queryExtraDataForTestTask( self ):

        workingDirectory = self._getWorkingDirectory()
        sceneFile = self._getSceneFileRelPath()

        if self.useFrames:
            frames = [ self.frames[0] ]
        else:
            frames = []

        extraData =          {      "pathRoot" : self.mainSceneDir,
                                    "startTask" : 0,
                                    "endTask" : 1,
                                    "totalTasks" : self.totalTasks,
                                    "outfilebasename" : self.outfilebasename,
                                    "sceneFile" : sceneFile,
                                    "width" : 1,
                                    "height": 1,
                                    "rtEngine": self.rtEngine,
                                    "useFrames": self.useFrames,
                                    "frames": frames,
                                    "parts": 1
                                }

        hash = "{}".format( random.getrandbits(128) )

        self.testTaskResPath = getTestTaskPath( self.rootPath )
        logger.debug( self.testTaskResPath )
        if not os.path.exists( self.testTaskResPath ):
            os.makedirs( self.testTaskResPath )

        return self._newComputeTaskDef( hash, extraData, workingDirectory, 0 )

  #######################
    def computationFinished( self, subtaskId, taskResult, dirManager = None ):

        tmpDir = dirManager.getTaskTemporaryDir( self.header.taskId, create = False )

        if len( taskResult ) > 0:
            numStart = self.subTasksGiven[ subtaskId ][ 'startTask' ]
            parts = self.subTasksGiven[ subtaskId ][ 'parts' ]
            numEnd = self.subTasksGiven[ subtaskId ][ 'endTask' ]
            self.subTasksGiven[ subtaskId ][ 'status' ] = 'finished'

            if self.useFrames and self.totalTasks <= len( self.frames ):
                framesList = self.subTasksGiven[ subtaskId ][ 'frames' ]

            for trp in taskResult:
                trFile = self._unpackTaskResult( trp, tmpDir )

                if not self.useFrames:
                    self.__collectImagePart( numStart, trFile )
                elif self.totalTasks <= len( self.frames ):
                    framesList = self.__collectFrames( numStart, trFile, framesList, parts )
                else:
                    self.__collectFramePart( numStart, trFile, parts, tmpDir )

            self.numTasksReceived += numEnd - numStart + 1

        if self.numTasksReceived == self.totalTasks:
            if self.useFrames:
                self.__copyFrames()
            else:
                outputFileName = u"{}".format( self.outputFile, self.outputFormat )
                self.__putImageTogether( outputFileName, self.collector )

    #######################
    def __collectAlphaFile( self, trFile, numStart ):
        if self.__useAlpha():
            if self.__useOuterTaskCollector():
                self.collectedAlphaFiles[ numStart ] = trFile
            else:
                self.collector.acceptAlpha( trFile )

    #######################
    def __collectTaskFile( self, trFile, numStart ):
        if self.__useOuterTaskCollector():
            self.collectedFileNames[ numStart ] = trFile
        else:
            self.collector.acceptTask( trFile )

    #######################
    def __useOuterTaskCollector( self ):
        unsupportedFormats = ['EXR', 'EPS']
        if self.outputFormat in unsupportedFormats:
            return True
        return False

    #######################
    def __useAlpha( self ):
        unsupportedFormats = ['BMP', 'PCX', 'PDF']
        if self.outputFormat in unsupportedFormats:
            return False
        return True

    #######################
    def _updateFramePreview(self, newChunkFilePath, frameNum ):
        num = self.frames.index(frameNum)

        if newChunkFilePath.endswith(".exr") or newChunkFilePath.endswith(".EXR"):
            img = exr_to_pil( newChunkFilePath )
        else:
            img = Image.open( newChunkFilePath )

        tmpDir = getTmpPath( self.header.clientId, self.header.taskId, self.rootPath )

        print num
        print os.path.join( tmpDir, "current_preview" )
        print len( self.previewFilePath )
        self.previewFilePath[ num ] = "{}{}".format( os.path.join( tmpDir, "current_preview" ), num )
        print self.previewFilePath[num]

        img.save( self.previewFilePath[ num ], "BMP" )

    #######################
    def __chooseFrames( self, frames, startTask, totalTasks ):
        if totalTasks <= len( frames ):
            subtasksFrames = int ( math.ceil( float( len( frames ) ) / float( totalTasks ) ) )
            startFrame = (startTask - 1) * subtasksFrames
            endFrame = min( startTask * subtasksFrames, len( frames ) )
            return frames[ startFrame:endFrame ], 1
        else:
            parts = totalTasks / len( frames )
            return [ frames[(startTask - 1 ) / parts ] ], parts

    #######################
    def __isAlphaFile(self, fileName ):
        return fileName.find('Alpha') != -1

    #######################
    def __putImageTogether( self, outputFileName, collector  ):

        if not self.__useOuterTaskCollector():
            collector.finalize().save( outputFileName, self.outputFormat )
            if not self.useFrames:
                self.previewFilePath = outputFileName
        else:
            self.collectedFileNames = OrderedDict( sorted( self.collectedFileNames.items() ) )
            self.collectedAlphaFiles = OrderedDict( sorted( self.collectedAlphaFiles.items() ) )
            files = " ".join( self.collectedFileNames.values() + self.collectedAlphaFiles.values() )
            self._putCollectedFilesTogether( outputFileName, files, "add" )

    #######################
    def __collectImagePart( self, numStart, trFile ):
        if self.__isAlphaFile( trFile ):
            self.__collectAlphaFile( trFile, numStart )
        else:
            self.__collectTaskFile( trFile, numStart )
            self._updatePreview( trFile )
            self._updateTaskPreview()

    #######################
    def __collectFrames( self, numStart, trFile, framesList, parts ):
        if self.__isAlphaFile( trFile ):
            return framesList
        else:
            self._updateFramePreview( trFile, framesList[0] )
            base, ext = os.path.splitext( trFile )
            outputFileName = u"{}.{}".format( base, self.outputFormat )
            if len( self.frames ) > self.totalTasks:
                self.collectedFileNames[ numStart ].append( outputFileName )
            else:
                self.collectedFileNames[ numStart ] = outputFileName
            if not self.__useOuterTaskCollector():
                collector = RenderingTaskCollector()
                collector.acceptTask( trFile )
                self.__putImageTogether( outputFileName, collector )
            else:
                files = trFile
                self._putCollectedFilesTogether( outputFileName, files, "add" )
            return framesList[1:]

    #######################
    def __collectFramePart( self, numStart, trFile, parts, tmpDir ):
        frameNum = self.frames[(numStart - 1 ) / parts ]
        part = ( ( numStart - 1 ) % parts ) + 1

        if self.__isAlphaFile( trFile ):
            pass
        else:
            self.framesGiven[ frameNum ][ part ] = trFile

        if len( self.framesGiven[ frameNum ] ) == parts:
            self.__putFrameTogether( tmpDir, frameNum, numStart )

    #######################
    def __copyFrames( self ):
        outpuDir = os.path.dirname( self.outputFile )
        if len( self.frames ) <= self.totalTasks:
            for file in self.collectedFileNames.values():
                shutil.copy( file, os.path.join( outpuDir, os.path.basename( file ) ) )
        else:
            for subtaskFiles in self.collectedFileNames.values():
                for file in subtaskFiles:
                    shutil.copy( file, os.path.join( outpuDir, os.path.basename( file ) ) )

    #######################
    def __putFrameTogether( self, tmpDir, frameNum, numStart ):
        outputFileName = os.path.join( tmpDir, self.__getOutputName( frameNum ) )
        if self.__useOuterTaskCollector():
            collected = self.framesGiven[ frameNum ]
            collected = OrderedDict( sorted( collected.items() ) )
            files = " ".join( collected.values() )
            self._putCollectedFilesTogether( outputFileName, files, "add" )
        else:
            collector = RenderingTaskCollector()
            for part in self.framesGiven[ frameNum ].values():
                collector.acceptTask( part )
            collector.finalize().save( outputFileName, self.outputFormat )
        self.collectedFileNames[ numStart ] = outputFileName
        self._updateFramePreview( outputFileName, frameNum )

    def __getOutputName( self, frameNum ):
        num = str( frameNum )
        return "{}{}.{}".format( self.outfilebasename, num.zfill( 4 ), self.outputFormat )
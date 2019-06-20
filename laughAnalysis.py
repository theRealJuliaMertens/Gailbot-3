'''
	Script that analyses a given audio file for laughter.
	Part of the Gailbot-3 development project.

	Developed by:

		Muhammad Umair								
		Tufts University
		Human Interaction Lab at Tufts

	Initial development: 6/8/19	
'''

import argparse 								# Library to extract input arguments
import os, sys 									# General system libraries.
import librosa									# Audio signal processing library.
import keras 									# Deep learning framework.

import matplotlib.pyplot as plt 				# Library to visualize mfcc features.
import librosa.display 							# Library to display signal.
import numpy 									# Library to have multi-dimensional homogenous arrays.
import scipy.signal as signal					# Used to apply the lowpass filter.
import tensorflow as tf 						# Deep neural network library
import operator
import logging
from termcolor import colored

# Gailbot scripts
import CHAT										# Script to produce CHAT files.

tf.get_logger().setLevel(logging.ERROR) 		# Turning off tensorflow debugging messages.

# Disabling any warnings.
def warn(*args, **kwargs):
    pass
import warnings
warnings.warn = warn

# *** Global variables / invariants ***

# Sampling rate for the time series that is loaded.
AUDIO_SAMPLE_RATE = 44100

# Path for the trained audio model in Hierarchical Data Format.
modelPath = './model.h5'


# *** Main driver functions ***

# Main driver function
# Input: jsonList constructed during Gailbot operation
# 		Uses dic['individualAudioFile']
def analyzeLaugh(infoList):
	# Loading the existing trained and compiled model to detect laughter.
	model = keras.models.load_model(modelPath)
	print(colored("\nAnalyzing laughter...",'red'))
	for dic in infoList:
		dic['jsonList'] = segmentLaugh(audioFile= dic['individualAudioFile'],
			modelPath=modelPath,outputPath=dic['outputDir'],
			threshold=CHAT.CHATVals['lowerBoundLaughAcceptance'],
			minLength=CHAT.CHATVals['LowerBoundLaughLength'],
			jsonList=dic['jsonList'],model=model)
	print(colored("Laughter analysis completed\n",'green'))
	return infoList

# Function that calls all relevant laughter analysis functions
# Inputs: Audio file name, trained audio model path, output Path,
#			Lower bound for laugh acceptance probability,
#			Minimum audio length to be classified as laughter.
#			Inidividual word jsonList
# Returns: Transcribed audio list / jsonList.
def segmentLaugh(audioFile, modelPath, outputPath,threshold, minLength,
	jsonList,model):
	print("Loading audio file: {0}".format(audioFile))

	# Loading the audio signal as a time series and obtaining its sampling rate.
	timeSeries, samplingRate = librosa.load(audioFile,sr =AUDIO_SAMPLE_RATE)

	# Getting a list of different audio features for analysis.
	featureList = getFeatureList(timeSeries,samplingRate)

	# Generating output prediction for input samples.
	probs = model.predict_proba(featureList,verbose=1)

	# Reshaping the tensor to the specified shape for further use in the neural 
	# network/
	probs = probs.reshape(len(probs))

	# Filtering the input signal using the butterworth filter.
	filtered = lowpass(probs)
	instances = getLaughterInstances(filtered, threshold, minLength)

	# Transcribing the laughter in the jsonList
	jsonList = transcribeLaugh(jsonList,instances)

	return jsonList


# *** Helper functions ***

# Function that extracts relevant time series features for analysis.
# Input: Time series, Series sampling rate.
# Returns: List of features.
def getFeatureList(timeSeries,samplingRate,window_size=37):
	
	# Computing MFCC features.
	mfccFeatures = computeMfccFeatures(timeSeries,samplingRate)
	# Computing delta features.
	deltaFeatures = computeDeltaFeatures(mfccFeatures)
	zeroPadMFCC = numpy.zeros((window_size,mfccFeatures.shape[1]))
	zeroPadDelta = numpy.zeros((window_size,deltaFeatures.shape[1]))
	paddedMFCCFeatures = numpy.vstack([zeroPadMFCC,mfccFeatures,zeroPadMFCC])
	paddedDeltaFeatures = numpy.vstack([zeroPadDelta,deltaFeatures,zeroPadDelta])
	featureList = []
	for i in range(window_size,len(mfccFeatures)+window_size):
		featureList.append(formatFeatures(paddedMFCCFeatures,paddedDeltaFeatures,
			i,window_size))
	featureList = numpy.array(featureList)
	return featureList


'''
	MFCC: Mel frequency cepstral coefficients.
	The MFCC are generated by using a fourier transform to convert the time series
	into the frequency domain and then taking the spectrum of this log using a
	cosine tranformation. 
	The resulting spectrum is in the qufrequency domain.
	It has a peak wherever there is a PERIODIC element in the original time series.
	This mel-scale used in the final transform is a perceptual scale based on 
	what human subjects can hear. It measures the percieved distance.

'''
# Function that extracts mfcc features for the given time series.
# Input: Time series, Series sampling rate.
# Returns: List of features.
def computeMfccFeatures(timeSeries, samplingRate):

	# Extractign the mel-frequency coefficients.
	# DCT type-II transform is used and 30 frequency bins are created.
	# Also computing a mel-sclaed spectogram.
	# Hop-length is the number of samples between successive frames. / columns of a spectogram.
	# The .T attribute is the transpose of the numpy array
	mfccFeatures = librosa.feature.mfcc(y=timeSeries,sr=samplingRate,
		n_mfcc=12,n_mels=12,hop_length=int(samplingRate/100),dct_type=2,n_fft=int(samplingRate/40)).T

	# Separating the complex valued Spectrogram D into its magnitude and phase components.
	# A complex valued spectogram does not have any negative frequency components.
	complexValuedMatrix = librosa.stft(timeSeries,hop_length = int(samplingRate/100))
	magnitude,phase = librosa.magphase(complexValuedMatrix)

	# Calculating the root-mean-square value / mean of the cosing function
	# Transposing the resultant matrix.
	rms = librosa.feature.rmse(S=magnitude).T

	# stacking the arrays horizontally and returns resultant feature list.
	return numpy.hstack([mfccFeatures,rms])


# Function that computes the delta features for the given time series.
# Generates the local estimate of the first and second derivative of the input 
# data along the selected axis.
# Input: Mel Frequency Cepstral Coefficients.
# Returns: Delta features.
def computeDeltaFeatures(mfccFeatures):
	return numpy.vstack([librosa.feature.delta(mfccFeatures.T),librosa.feature.delta(mfccFeatures.T, order=2)]).T

# Function that formats mfcc and delta features in the correct format to use.
def formatFeatures(mfccFeatures, deltaFeatures,index, window_size=37):
    return numpy.append(mfccFeatures[index-window_size:index+window_size],deltaFeatures[index-window_size:index+window_size])

# Applying a lowpass filter to the audio.
def lowpass(sig, filter_order = 2, cutoff = 0.01):
	#Set up Butterworth filter

	filter_order  = 2

	# Create a butterworth filter of the second order with 
	# ba (numerator/denominator) output.
	B, A = signal.butter(filter_order, cutoff, output='ba')

	# Applies the linear filter twice to the signal, 
	# Once forwards, and once backwards.
	return(signal.filtfilt(B,A, sig))

# Extracts laughter from the filtered audio.
def frame_span_to_time_span(frame_span):
    return (frame_span[0] / 100., frame_span[1] / 100.)

def collapse_to_start_and_end_frame(instance_list):
    return (instance_list[0], instance_list[-1])

def getLaughterInstances(probs, threshold = 0.5, minLength = 0.2):
	instances = []
	current_list = []
	for i in range(len(probs)):
		if numpy.min(probs[i:i+1]) > threshold:
			current_list.append(i)
		else:
			if len(current_list) > 0:
				instances.append(current_list)
				current_list = []
	instances = [frame_span_to_time_span(collapse_to_start_and_end_frame(i)) for i in instances if len(i) > minLength]
	return instances

# Function that transcribes laughter in the list
def transcribeLaugh(jsonList,instances):
	newInst = []
	for instance in instances: 
		newInst.append([jsonList[1][0],instance[0],instance[1],"[^ LAUGHTER ]"])
	for instance in newInst:jsonList.append(instance)
	jsonList[1:] = sorted(jsonList[1:], key = operator.itemgetter(1))
	return jsonList















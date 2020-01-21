import numpy as np
import random as rn

# The below is necessary in Python 3.2.3 onwards to
# have reproducible behavior for certain hash-based operations.
# See these references for further details:
# https://docs.python.org/3.4/using/cmdline.html#envvar-PYTHONHASHSEED
# https://github.com/fchollet/keras/issues/2280#issuecomment-306959926

import os

# os.environ['PYTHONHASHSEED'] = '0'

# The below is necessary for starting Numpy generated random numbers
# in a well-defined initial state.

np.random.seed(421)

# The below is necessary for starting core Python generated random numbers
# in a well-defined state.

rn.seed(123451)

import logging

from keras import regularizers
from keras.layers import Bidirectional, Dense, Dropout, Embedding, LSTM, TimeDistributed
from keras.models import Sequential, load_model

from data.datasets import *
from eval import keras_metrics, metrics
from nlp import tokenizer as tk
from utils import info, preprocessing, postprocessing, plots

# LOGGING CONFIGURATION

logging.basicConfig(
    format='%(asctime)s\t%(levelname)s\t%(message)s',
    level=logging.DEBUG)

info.log_versions()

# END LOGGING CONFIGURATION

# GLOBAL VARIABLES

SAVE_MODEL = False
MODEL_PATH = "models/simplernn.h5"
SHOW_PLOTS = False

# END GLOBAL VARIABLES

# Dataset and hyperparameters for each dataset

DATASET = Hulth

if DATASET == Semeval2017:
    tokenizer = tk.tokenizers.nltk
    DATASET_FOLDER = "data/Semeval2017"
    MAX_DOCUMENT_LENGTH = 400
    MAX_VOCABULARY_SIZE = 20000
    EMBEDDINGS_SIZE = 50
    BATCH_SIZE = 32
    EPOCHS = 30
    KP_WEIGHT = 10
    STEM_MODE = metrics.stemMode.both
    STEM_TEST = False
elif DATASET == Hulth:
    tokenizer = tk.tokenizers.nltk
    DATASET_FOLDER = "data/Hulth2003"
    MAX_DOCUMENT_LENGTH = 550
    MAX_VOCABULARY_SIZE = 20000
    EMBEDDINGS_SIZE = 300
    BATCH_SIZE = 32
    EPOCHS = 28
    KP_WEIGHT = 10
    STEM_MODE = metrics.stemMode.none
    STEM_TEST = False
elif DATASET == Marujo2012:
    tokenizer = tk.tokenizers.nltk
    DATASET_FOLDER = "data/Marujo2012"
    MAX_DOCUMENT_LENGTH = 7000
    MAX_VOCABULARY_SIZE = 20000
    EMBEDDINGS_SIZE = 50
    BATCH_SIZE = 16
    EPOCHS = 10
    KP_WEIGHT = 10
    STEM_MODE = metrics.stemMode.both
    STEM_TEST = False
elif DATASET == Semeval2010:
    tokenizer = tk.tokenizers.nltk
    DATASET_FOLDER = "data/Semeval2010"
    MAX_DOCUMENT_LENGTH = 16600
    MAX_VOCABULARY_SIZE = 50000
    EMBEDDINGS_SIZE = 50
    BATCH_SIZE = 16
    EPOCHS = 40
    KP_WEIGHT = 500
    STEM_MODE = metrics.stemMode.results
    STEM_TEST = True
else:
    raise NotImplementedError("Can't set the hyperparameters: unknown dataset")

# END PARAMETERS

logging.info("Loading dataset...")

data = DATASET(DATASET_FOLDER)

train_doc_str, train_answer_str = data.load_train()
test_doc_str, test_answer_str = data.load_test()
val_doc_str, val_answer_str = data.load_validation()

train_doc, train_answer = tk.tokenize_set(train_doc_str, train_answer_str, tokenizer)
test_doc, test_answer = tk.tokenize_set(test_doc_str, test_answer_str, tokenizer)
val_doc, val_answer = tk.tokenize_set(val_doc_str, val_answer_str, tokenizer)

# Sanity check
# logging.info("Sanity check: %s",metrics.precision(test_answer,test_answer))

logging.info("Dataset loaded. Preprocessing data...")

train_x, train_y, test_x, test_y, val_x, val_y, embedding_matrix = preprocessing. \
    prepare_sequential(train_doc, train_answer, test_doc, test_answer, val_doc, val_answer,
                       max_document_length=MAX_DOCUMENT_LENGTH,
                       max_vocabulary_size=MAX_VOCABULARY_SIZE,
                       embeddings_size=EMBEDDINGS_SIZE,
                       stem_test=STEM_TEST)

# weigh training examples: everything that's not class 0 (not kp)
# gets a heavier score
from sklearn.utils import class_weight

train_y_weights = np.argmax(train_y, axis=2)
train_y_weights = np.reshape(class_weight.compute_sample_weight('balanced', train_y_weights.flatten()),
                             np.shape(train_y_weights))

logging.info("Data preprocessing complete.")
logging.info("Maximum possible recall: %s",
             metrics.recall(test_answer,
                            postprocessing.get_words(test_doc, postprocessing.undo_sequential(test_y)),
                            STEM_MODE))

if not SAVE_MODEL or not os.path.isfile(MODEL_PATH):

    logging.debug("Building the network...")
    model = Sequential()

    embedding_layer = Embedding(np.shape(embedding_matrix)[0],
                                EMBEDDINGS_SIZE,
                                weights=[embedding_matrix],
                                input_length=MAX_DOCUMENT_LENGTH,
                                trainable=False)

    model.add(embedding_layer)
    model.add(Bidirectional(LSTM(300, activation='tanh', recurrent_activation='hard_sigmoid', return_sequences=True)))
    model.add(Dropout(0.25))
    model.add(TimeDistributed(Dense(150, activation='relu', kernel_regularizer=regularizers.l2(0.01))))
    model.add(Dropout(0.25))
    model.add(TimeDistributed(Dense(3, activation='softmax')))

    logging.info("Compiling the network...")
    model.compile(loss='categorical_crossentropy', optimizer='rmsprop', metrics=['accuracy'],
                  sample_weight_mode="temporal")
    print(model.summary())

    metrics_callback = keras_metrics.MetricsCallback(val_x, val_y)

    logging.info("Fitting the network...")

    history = model.fit(train_x, train_y,
                        validation_data=(val_x, val_y),
                        epochs=EPOCHS,
                        batch_size=BATCH_SIZE,
                        sample_weight=train_y_weights,
                        callbacks=[metrics_callback])

    if SHOW_PLOTS:
        plots.plot_accuracy(history)
        plots.plot_loss(history)
        plots.plot_prf(metrics_callback)

    if SAVE_MODEL:
        model.save(MODEL_PATH)
        logging.info("Model saved in %s", MODEL_PATH)

else:
    logging.info("Loading existing model from %s...", MODEL_PATH)
    model = load_model(MODEL_PATH)
    logging.info("Completed loading model from file")

logging.info("Predicting on test set...")
output = model.predict(x=test_x, verbose=1)
logging.debug("Shape of output array: %s", np.shape(output))

obtained_tokens = postprocessing.undo_sequential(output)
obtained_words = postprocessing.get_words(test_doc, obtained_tokens)

precision = metrics.precision(test_answer, obtained_words,STEM_MODE)
recall = metrics.recall(test_answer, obtained_words,STEM_MODE)
f1 = metrics.f1(precision, recall)

print("###    Obtained Scores    ###")
print("###     (full dataset)    ###")
print("###")
print("### Precision : %.4f" % precision)
print("### Recall    : %.4f" % recall)
print("### F1        : %.4f" % f1)
print("###                       ###")

keras_precision = keras_metrics.keras_precision(test_y, output)
keras_recall = keras_metrics.keras_recall(test_y, output)
keras_f1 = keras_metrics.keras_f1(test_y, output)

print("###    Obtained Scores    ###")
print("###    (fixed dataset)    ###")
print("###")
print("### Precision : %.4f" % keras_precision)
print("### Recall    : %.4f" % keras_recall)
print("### F1        : %.4f" % keras_f1)
print("###                       ###")

clean_words = postprocessing.get_valid_patterns(obtained_words)

precision = metrics.precision(test_answer, clean_words,STEM_MODE)
recall = metrics.recall(test_answer, clean_words,STEM_MODE)
f1 = metrics.f1(precision, recall)

print("###    Obtained Scores    ###")
print("### (full dataset,        ###")
print("###  pos patterns filter) ###")
print("###")
print("### Precision : %.4f" % precision)
print("### Recall    : %.4f" % recall)
print("### F1        : %.4f" % f1)
print("###                       ###")

obtained_words_top = postprocessing.get_top_words(test_doc, output, 5)

precision_top = metrics.precision(test_answer, obtained_words_top,STEM_MODE)
recall_top = metrics.recall(test_answer, obtained_words_top,STEM_MODE)
f1_top = metrics.f1(precision_top, recall_top)

print("###    Obtained Scores    ###")
print("### (full dataset, top 5) ###")
print("###")
print("### Precision : %.4f" % precision_top)
print("### Recall    : %.4f" % recall_top)
print("### F1        : %.4f" % f1_top)
print("###                       ###")

obtained_words_top = postprocessing.get_top_words(test_doc, output, 10)

precision_top = metrics.precision(test_answer, obtained_words_top,STEM_MODE)
recall_top = metrics.recall(test_answer, obtained_words_top,STEM_MODE)
f1_top = metrics.f1(precision_top, recall_top)

print("###    Obtained Scores    ###")
print("### (full dataset, top 10)###")
print("###")
print("### Precision : %.4f" % precision_top)
print("### Recall    : %.4f" % recall_top)
print("### F1        : %.4f" % f1_top)
print("###                       ###")

obtained_words_top = postprocessing.get_top_words(test_doc, output, 15)

precision_top = metrics.precision(test_answer, obtained_words_top,STEM_MODE)
recall_top = metrics.recall(test_answer, obtained_words_top,STEM_MODE)
f1_top = metrics.f1(precision_top, recall_top)

print("###    Obtained Scores    ###")
print("### (full dataset, top 15)###")
print("###")
print("### Precision : %.4f" % precision_top)
print("### Recall    : %.4f" % recall_top)
print("### F1        : %.4f" % f1_top)
print("###                       ###")

if DATASET == Semeval2017:
    print("### SEMEVAL ANNOTATOR ###")
    print("###        All        ###")

    from eval import anno_generator

    anno_generator.write_anno("/tmp/simplernn", test_doc_str, obtained_words)
    from data.Semeval2017 import eval

    eval.calculateMeasures("data/Semeval2017/test", "/tmp/simplernn-all", remove_anno=["types"])

    print("###     Filtered      ###")
    anno_generator.write_anno("/tmp/simplernn-clean", test_doc_str, clean_words)
    eval.calculateMeasures("data/Semeval2017/test", "/tmp/simplernn-clean", remove_anno=["types"])

    print("###      Top 15       ###")
    anno_generator.write_anno("/tmp/simplernn-15", test_doc_str, obtained_words_top)
    eval.calculateMeasures("data/Semeval2017/test", "/tmp/simplernn-15", remove_anno=["types"])

    print("###  Top 15 Filtered  ###")
    clean_words = postprocessing.get_valid_patterns(obtained_words_top)

    anno_generator.write_anno("/tmp/simplernn-15-clean", test_doc_str, clean_words)
    eval.calculateMeasures("data/Semeval2017/test", "/tmp/simplernn-15-clean", remove_anno=["types"])

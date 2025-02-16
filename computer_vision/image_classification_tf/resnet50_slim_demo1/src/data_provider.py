# -*- coding: utf-8 -*-
"""
Created on Thu Oct 11 21:43:47 2018


@author: zyb_as 
"""
import os
import tensorflow as tf
import data_augmentation_tf as augmentation


def datset_input_fn_train(filenames, batch_size, epochs_num):
    dataset=tf.data.TFRecordDataset(filenames)

    def parser_train(record):
        keys_to_features={
            'image/class/label':tf.FixedLenFeature(shape=(), dtype=tf.int64),
            'image/encoded':tf.FixedLenFeature(shape=(), dtype=tf.string),  
            'image/shape':tf.FixedLenFeature(shape=(3,), dtype=tf.int64)
        }
        parsed = tf.parse_single_example(record, keys_to_features)
        # get image raw data
        image = tf.decode_raw(parsed["image/encoded"], tf.uint8) ###### img_raw
        # The type is now uint8 but we need it to be float.
        #image = tf.cast(image, tf.float32)
        # get image shape
        shape = parsed["image/shape"]
        # reshape
        image=tf.reshape(image, shape=shape)

        # do data augmentation
        augmentation_image = augmentation.augmentation(image, img_shape=shape, is_training=True)
        # get image class label
        label = parsed["image/class/label"]
        return augmentation_image, label

    dataset = dataset.map(parser_train)
    dataset = dataset.shuffle(buffer_size=1024)
    dataset = dataset.batch(batch_size)
    dataset = dataset.repeat(epochs_num)
    iterator = dataset.make_one_shot_iterator()
    return iterator



def datset_input_fn_valid(filenames, batch_size, epochs_num):
    dataset=tf.data.TFRecordDataset(filenames)

    def parser_valid(record):
        keys_to_features={
            'image/class/label':tf.FixedLenFeature(shape=(), dtype=tf.int64),
            'image/encoded':tf.FixedLenFeature(shape=(), dtype=tf.string),  
            'image/shape':tf.FixedLenFeature(shape=(3,), dtype=tf.int64)
        }
        parsed = tf.parse_single_example(record, keys_to_features)
        # get image raw data
        image = tf.decode_raw(parsed["image/encoded"], tf.uint8) ###### img_raw
        # The type is now uint8 but we need it to be float.
        #image = tf.cast(image, tf.float32)
        # get image shape
        shape = parsed["image/shape"]
        # reshape
        image=tf.reshape(image, shape=shape)

        # do data augmentation
        augmentation_image = augmentation.augmentation(image, img_shape=shape, is_training=False)
        # get image class label
        label = parsed["image/class/label"]
        return augmentation_image, label

    dataset = dataset.map(parser_valid)
    dataset = dataset.batch(batch_size)
    dataset = dataset.repeat(epochs_num)
    #iterator = dataset.make_initializable_iterator()
    iterator = dataset.make_one_shot_iterator()
    return iterator



def get_train_data_op(tfrecord_dir, batch_size, epochs_num):
    #Get op of train data

    # build tfrecord file namelist  
    record_name_list = []
    for tfrecord_file in os.listdir(tfrecord_dir):
        is_train = tfrecord_file.find("train")
        if is_train != -1:
            record_name_list.append(tfrecord_file)
    # get tfrecord file path list
    record_path_list=[]
    for record_name in record_name_list:
        record_path_list.append(os.path.join(tfrecord_dir, record_name))
    # get batch data iterator
    train_iterator = datset_input_fn_train(filenames=record_path_list, 
        batch_size=batch_size, epochs_num=epochs_num)
    train_feature, train_label = train_iterator.get_next()
    return train_feature, train_label


def get_valid_data_op(tfrecord_dir, batch_size, epochs_num):
    # Get op of validation data
    # build tfrecord file namelist
    record_name_list = []
    for tfrecord_file in os.listdir(tfrecord_dir):
        is_train = tfrecord_file.find("validation")
        if is_train != -1:
            record_name_list.append(tfrecord_file)
    # get tfrecord file path list
    record_path_list=[]
    for record_name in record_name_list:
        record_path_list.append(os.path.join(tfrecord_dir, record_name))
    # get batch data iterator
    test_iterator = datset_input_fn_valid(filenames=record_path_list, 
        batch_size=batch_size, epochs_num=epochs_num)
    test_feature, test_label = test_iterator.get_next()
    return test_feature, test_label

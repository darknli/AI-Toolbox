# -*- coding: utf-8 -*-
from __future__ import division
"""
Created on Thu Oct 11 17:21:35 2018

@author: zyb_as 
"""

"""Train a CNN classification model via pretrained ResNet-50 model.

Example Usage:
---------------
python3 train.py \
    --checkpoint_path: Path to pretrained ResNet-50 model.
    --record_path: Path to training tfrecord file.
    --logdir: Path to log directory.
"""

import os
import sys
import math
import time
import numpy as np
from PIL import Image
import tensorflow as tf
from tensorflow.contrib.slim import nets
from tensorflow.python.ops import control_flow_ops

import resnet_v1_50_model
import data_provider


slim = tf.contrib.slim
flags = tf.app.flags

# TODO: Modify parameter defaults here or specify them directly at call time
flags.DEFINE_string('tf_record_dir', 
                    '/home/ansheng/cv_strategy/porn_detect/cnn_tf/' +
                    'resnet50_slim/tfrecord',
                    'Directory to tfrecord files.')
flags.DEFINE_string('checkpoint_path', 
                    '/home/ansheng/cv_strategy/model_zoo/' +
                    'resnet_v1_50.ckpt', 
                    'Path to pretrained ResNet-50 model.')
flags.DEFINE_string('label_path',
                    '/home/ansheng/cv_strategy/porn_detect/cnn_tf/' +
                    'classification_by_slim/tfrecord/labels.txt',
                    'Path to label file.')
flags.DEFINE_string('log_dir', './log/train_log', 'Path to log directory.')
flags.DEFINE_string('gpu_device', '0', 'Specify which gpu to be used')
flags.DEFINE_float('learning_rate', 0.001, 'Initial learning rate.')
flags.DEFINE_float(
    'learning_rate_decay_factor', 0.1, 'Learning rate decay factor.')  # TODO: not use
flags.DEFINE_integer(
    'num_epochs_per_decay', 3,
    'Number of epochs after which learning rate decays. Note: this flag counts '  # TODO: not use
    'epochs per clone but aggregates per sync replicas. So 1.0 means that '
    'each clone will go over full epoch individually, but replicas will go '
    'once across all replicas.')
flags.DEFINE_integer('num_classes', 2, 'Number of classes')
flags.DEFINE_integer('epoch_num', 10, 'Number of epochs.')
flags.DEFINE_integer('batch_size', 48, 'Batch size')

FLAGS = flags.FLAGS


def get_learning_rate(epoch_step, cur_learning_rate, lr_decay_factor, num_epochs_per_decay):
    """get the learning rate.
    """
    if epoch_step == 0:
        return cur_learning_rate

    lr = cur_learning_rate
    if epoch_step % num_epochs_per_decay == 0:
        lr *= lr_decay_factor
        print("learning rate adjustment from {} to {}".format(cur_learning_rate, lr))
    return lr
    

def main(_):
    # Specify which gpu to be used
    os.environ["CUDA_VISIBLE_DEVICES"] = FLAGS.gpu_device

    model_ckpt_path = FLAGS.checkpoint_path # Path to the pretrained model
    model_save_dir = FLAGS.log_dir  # Path to the model.ckpt-(num_steps) will be saved
    tensorboard_summary_dir = os.path.join(model_save_dir, 'tensorboard_summary')
    tf_record_dir = FLAGS.tf_record_dir
    batch_size = FLAGS.batch_size
    num_classes = FLAGS.num_classes
    epoch_num = FLAGS.epoch_num
    init_learning_rate = FLAGS.learning_rate
    lr_decay_factor = FLAGS.learning_rate_decay_factor
    num_epochs_per_decay = FLAGS.num_epochs_per_decay
    
    # check directory 
    if not tf.gfile.Exists(model_save_dir):
        tf.gfile.MakeDirs(model_save_dir)
    else:
        print("warning! log_dir has exist!")
    tf.gfile.MakeDirs(tensorboard_summary_dir)

    # create placeholders
    inputs = tf.placeholder(tf.float32, shape=[None, 224, 224, 3], name='inputs')
    labels = tf.placeholder(tf.int32, shape=[None], name='labels')
    is_training = tf.placeholder(tf.bool, name='is_training')
    learning_rate = tf.placeholder(tf.float32, name='learning_rate')
    
    # build model correlation op: logits, classed, loss, acc
    classification_model = resnet_v1_50_model.Model(num_classes=num_classes)

    #inputs_dict = { 'inputs': inputs,
    #                'is_training': is_training}
    inputs_dict = classification_model.preprocess(inputs, is_training)
    predict_dict = classification_model.predict(inputs_dict)

    loss_dict = classification_model.loss(predict_dict, labels)
    #loss_dict = classification_model.focal_loss(predict_dict, labels)
    loss = loss_dict['loss']

    postprocessed_dict = classification_model.postprocess(predict_dict)
    accuracy = classification_model.accuracy(postprocessed_dict, labels)


    # set training correlation parameters 
    global_step = tf.Variable(0, trainable=False, name='global_step', dtype=tf.int64)
    optimizer = tf.train.AdamOptimizer(learning_rate=learning_rate)
    #train_step = optimizer.minimize(loss)

    # these three line can fix the low valid accuarcy bug when set is_training=False
    # this bug is cause by use of BN, see for more: https://blog.csdn.net/jiruiYang/article/details/77202674
    update_ops = tf.get_collection(tf.GraphKeys.UPDATE_OPS)
    with tf.control_dependencies([tf.group(*update_ops)]):
        train_step = optimizer.minimize(loss, global_step)
    

    # init Saver to restore and save model
    checkpoint_exclude_scopes = 'Logits'
    exclusions = None
    if checkpoint_exclude_scopes:
        exclusions = [
            scope.strip() for scope in checkpoint_exclude_scopes.split(',')]
    variables_to_restore = []
    for var in slim.get_model_variables():
        excluded = False
        for exclusion in exclusions:
            if var.op.name.startswith(exclusion):
                excluded = True
        if not excluded:
            variables_to_restore.append(var)

    saver_restore = tf.train.Saver(var_list=variables_to_restore)
    
    saver = tf.train.Saver(tf.global_variables())
    
    init = tf.global_variables_initializer()

    # config and start session
    config = tf.ConfigProto() 
    config.gpu_options.allow_growth=True
    config.gpu_options.per_process_gpu_memory_fraction = 0.5
    with tf.Session(config=config) as sess:
        sess.run(init)
        
        # Load the pretrained checkpoint file xxx.ckpt
        saver_restore.restore(sess, model_ckpt_path)
        
        total_batch_num = 0
        total_best_acc = 0
        cur_lr = init_learning_rate
        for epoch in range(epoch_num):
            ####################
            # training one epoch
            ####################

            print("start training epoch {0}...".format(epoch+1))
            sys.stdout.flush()
            epoch_start_time = time.time()

            # get next train batch op
            train_feature, train_label = data_provider.get_train_data_op(tf_record_dir, batch_size, 1) 

            # get current epoch's learning rate
            cur_lr = get_learning_rate(epoch, cur_lr, lr_decay_factor, num_epochs_per_decay)

            # training batch by batch until one epoch finish
            batch_num = 0
            loss_sum = 0
            acc_sum = 0
            while True: 
                # get a new batch data
                try:
                    images, groundtruth_lists = sess.run([train_feature, train_label]) 
                        
                    total_batch_num += 1
                    batch_num += 1
                except tf.errors.OutOfRangeError:
                    print("epoch {0} training finished.".format(epoch + 1)) 
                    sys.stdout.flush()
                    break

                train_dict = {inputs: images, 
                                labels: groundtruth_lists,
                                is_training: True,
                                learning_rate: cur_lr}
                loss_, acc_, _ = sess.run([loss, accuracy, train_step], feed_dict=train_dict)

                loss_sum += loss_
                loss_ = loss_sum / batch_num
                acc_sum += acc_
                acc_ = acc_sum / batch_num
                
                train_text = 'Step: {}, Loss: {:.4f}, Accuracy: {:.4f}'.format(
                    batch_num, loss_, acc_)
                print(train_text)
                sys.stdout.flush()

                #loss_summary.value.add(tag="train_loss", simple_value = loss_)
                #acc_summary.value.add(tag="train_accuary", simple_value = acc_)
                #train_writer.add_summary(loss_summary, total_batch_num)
                #train_writer.add_summary(acc_summary, total_batch_num)

            epoch_end_time = time.time()
            print("total use time: {}s\n".format(int(epoch_end_time - epoch_start_time)))

            ####################
            # validation one epoch
            ####################

            print("start validation, please wait...")
            sys.stdout.flush()

            # get next valid batch op
            valid_feature, valid_label = data_provider.get_valid_data_op(tf_record_dir, batch_size, 1)
            #sess.run(valid_iterator.initializer) # we use make_initializable_iterator, so should be init before use

            # valid batch by batch until validation dataset finish
            batch_num = 0
            loss_sum, loss_mean = 0, 0
            acc_sum, acc_mean = 0, 0
            while True: 
                # get a new batch data
                try:
                    valid_images, valid_groundtruth_lists = sess.run([valid_feature, valid_label]) 
                    batch_num += 1
                except tf.errors.OutOfRangeError:
                    # compute mean accuracy
                    loss_mean = loss_sum / batch_num
                    acc_mean = acc_sum / batch_num
                    print("validation finished. Valid loss:{:.5f}, Valid accuracy:{:.5f}".format(
                        loss_mean, acc_mean)) 
                    sys.stdout.flush()
                    
                    # summary validation accuracy
                    #valid_acc_summary.value.add(tag="valid_accuary", simple_value = acc_mean)
                    #train_writer.add_summary(valid_acc_summary, epoch)
                    break

                valid_dict = {inputs: valid_images, 
                              labels: valid_groundtruth_lists,
                              is_training: False}
                
                valid_loss_, valid_acc_ = sess.run([loss, accuracy], feed_dict=valid_dict)
                loss_sum += valid_loss_
                acc_sum += valid_acc_
                

            if acc_mean > total_best_acc:
                print("epoch {}: val_acc improved from {:.5f} to {:.5f}".format(epoch+1, total_best_acc, acc_mean))
                sys.stdout.flush()
                total_best_acc = acc_mean

                ckpt_name = "resnet50-zyb_v1-epoch{0}.ckpt".format(epoch+1)
                model_save_path = os.path.join(model_save_dir, ckpt_name)
                #saver.save(sess, model_save_path, global_step = total_batch_num) # TODO: global_step?
                saver.save(sess, model_save_path, global_step=global_step) # TODO: global_step?
                print('save mode to {}'.format(model_save_path))
                sys.stdout.flush()
            else:
                print("epoch {}: val_acc did not improve from {}".format(epoch+1, total_best_acc))
                sys.stdout.flush()

            time.sleep(120) # let gpu take a breath
            print("\n\n")
            sys.stdout.flush()
    

if __name__ == '__main__':
    tf.app.run()


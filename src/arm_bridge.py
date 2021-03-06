#!/usr/bin/env python

'''
Created on: 12 Sep 2012
Author: Olivier Kermorgant

Bridge to control arm position and velocity 

Subscribes:
- robot position or velocity command on topic /main_control/command

Publishes:
- robot joint positions commands on topic /joint_control/command (position control)
'''

# modules
# ROS stuff and multithreading
import roslib
import message_filters
import rospy,time,threading
from sensor_msgs.msg import JointState
from baxter_core_msgs.msg import JointCommand
# math
from pylab import arange, sign
# system
import sys,os


verbose = True

# low-level sampling time
T = 1./200

# joint data: read URDF to get joint names and limits (position + velocity)
urdf = rospy.get_param("/robot_description").splitlines()
N = 0
jointNames = []
jointMin = []
jointMax = []
jointVelMax = []
inJoint = False
jName = ''
for ui in urdf:
    if inJoint:
        if 'limit' in ui:
            jointNames.append(jName)
            N += 1
            s = ui.split('"')
            for i in range(len(s)):
                if 'lower' in s[i]:
                    jointMin.append(float(s[i+1]))
                elif 'upper' in s[i]:
                    jointMax.append(float(s[i+1]))
                elif 'velocity' in s[i]:
                    jointVelMax.append(float(s[i+1]))
            inJoint = False
        elif 'mimic' in ui:
            inJoint = False
    else:
        if 'joint name=' in ui and 'fixed' not in ui:
                jName = ui.split('"')[1]
                inJoint = True

# update max velocity according to sample time T
jointVelMax = [T*v for v in jointVelMax]

current_qStates = [0]*N

print("Initializing bridge with " + str(N) + " joints")

def inJointLimits(cmd, names):
    global current_qStates
    
    for i in range(N):
        for j in range(len(names)):
            if names[j] == jointNames[i]:
                current_qStates[i] = min(max(cmd[j], jointMin[i]), jointMax[i])
    '''
    Returns the position q projected inside the joint limits
    '''
    return current_qStates

class State:
    def __init__(self):
          self.qSet = [0.]*N
          self.cmdCount = 0
          self.t0 = rospy.Time.now().to_sec()

    def followPosition(self, qDes, cmdCountCur):
        '''
        Follows the joint position setpoint as long as :
        - the corresponding position lies inside the joint limits
        - no other command has been received
        '''
        # build trajectory to go from qSet to qDes with max velocity
        qTraj = []
        for i in range(N):
            if self.qSet[i] == qDes[i]:
                qTraj.append([])
            else:
                qTraj.append(list(arange(self.qSet[i],qDes[i],sign(qDes[i]-self.qSet[i])*jointVelMax[i])[1:]))
        for i in range(N):
            if len(qTraj[i]) == 0:
                qTraj[i].append(qDes[i])
            elif qTraj[i][-1] != qDes[i]:
                qTraj[i].append(qDes[i])
        steps = max([len(t) for t in qTraj])
        for i in range(N):
            qTraj[i] += [qDes[i]] * (steps - len(qTraj[i]))

        # follow trajectory from qSet to qDes
        k = 0
        while (self.cmdCount == cmdCountCur) and not rospy.is_shutdown() and k < len(qTraj[0]):
            # running setpoint
            self.qSet = [qTraj[i][k] for i in range(N)]
            k = k+1
            time.sleep(T)
        

    def followVelocity(self, data, cmdCountCur):
        '''
        Follows the joint velocity setpoint as long as :
        - the corresponding position lies inside the joint limits
        - no other command has been received
        '''
        qDot = [data.command[i] * T for i in range(len(data.command))]
        q0 = [0]*len(qDot)
        # ensures max velocity
        for i in range(N):
            for j in range(len(q0)):
                if data.names[j] == jointNames[i]:
                    q0[j] = self.qSet[i]
                    if qDot[j] > jointVelMax[i]:
                        qDot[j] = jointVelMax[i]
                    elif -qDot[j] > jointVelMax[i]:
                        qDot[j] = -jointVelMax[i]
        k = 0
        
                    
        while (self.cmdCount == cmdCountCur) and not rospy.is_shutdown():
            k = k+1
            # running setpoint
            self.qSet = inJointLimits([q0[i]+k*qDot[i] for i in range(len(q0))], data.names)
            time.sleep(T)
    
  
    def readBridgeCommand(self, data):
        '''
        Execute command received on /robot/command topic
        '''
      
        if self.cmdCount == 0:
            print('Switching to control mode')
        self.cmdCount += 1
            
        self.t0 = rospy.Time.now().to_sec()  
            

        if data.mode == 2:
            # read velocities
            thread=threading.Thread(group=None,target=self.followVelocity, name=None, args=(data, self.cmdCount), kwargs={})
            thread.start()
        elif data.mode == 1:
                # read positions
                thread=threading.Thread(group=None,target=self.followPosition, name=None, args=(inJointLimits(data.command, data.names), self.cmdCount), kwargs={})
                thread.start()
            
            
if __name__ == '__main__':
    '''
    Begin of main code
    '''
    
    # name of the node
    rospy.init_node('joint_control')
        
    state = State()

    # subscribe to left arm
    rospy.Subscriber('/robot/limb/left/joint_command', JointCommand, state.readBridgeCommand)
        
    # subscribe to right arm
    rospy.Subscriber('/robot/limb/right/joint_command', JointCommand, state.readBridgeCommand)
    
    # publish position command depending on the simulator type
    cmdPub = rospy.Publisher('/joint_states', JointState, queue_size = 1)
        
    # create JointState object - used in rviz / ViSP
    jointState = JointState()
    jointState.position = [0.]*N
    jointState.name = jointNames

    print('Waiting commands')

    while not rospy.is_shutdown():   
        # publish current position command to the simulator
        jointState.position = state.qSet
        jointState.header.stamp = rospy.Time.now()
        cmdPub.publish(jointState)

        # should not do any other thing
        #print 'listening for new command'
        rospy.sleep(T)

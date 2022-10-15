# General-purpose Scan Tool for the FLASH linac at DESY

## Overview

The code provides three basic classes which correspond to abstract representations of actuators, sensors/detectors and 
processes (i.e. a sequence of basic operations with actuators and sensors), with a view towards the composition of 
end-user applications combining the control of hardware components and data acquisition. A simple GUI enables a 
straighforward configuration of scans. Interaction with machine components is implemented with the Python bindings using 
the C++ DOOCS client API (pydoocs). The code is currently in a testing phase. 


![GUI snapshot](gui_snapshot.png?raw=true "Title")

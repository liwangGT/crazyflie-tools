function [d imFnames]=lcmlog_2015_04_14_02()
full_fname = 'lcmlog_2015_04_14_02.mat';
fname = '/home/drc/code/crazyflie-tools/logs/cf2/tests0414/lcmlog_2015_04_14_02.mat';
if (exist(full_fname,'file'))
    filename = full_fname;
else
    filename = fname;
end
d = load(filename);

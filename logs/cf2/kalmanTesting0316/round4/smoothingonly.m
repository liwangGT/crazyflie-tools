function [d imFnames]=smoothingonly()
full_fname = 'logs/cf2/kalmanTesting0316/round4/smoothingonly.mat';
fname = '/home/blandry/code/crazyflie-tools/logs/cf2/kalmanTesting0316/round4/smoothingonly.mat';
if (exist(full_fname,'file'))
    filename = full_fname;
else
    filename = fname;
end
d = load(filename);

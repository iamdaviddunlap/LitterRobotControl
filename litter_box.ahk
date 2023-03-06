^F19::Trigger_Cleaning("CLEANING")

Trigger_Cleaning(run_mode) {
  Run, %comspec% /c "C:\Users\David\Documents\Personal Projects\LitterRobotControl\litter_robot_sync.py" %run_mode%, , Hide
  WinWaitClose, ahk_pid %ErrorLevel%
  return
}
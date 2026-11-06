`/home/user/project/shabi_forest/changes/2_thb_netflix_selfval` contains thb's "netflix benchmark" + a simple claudecode loop engineering worker working on the task, aiming to make the task completed. and then evaluated on bench mark tests. then claude code chat interact with human take screenshot and make the final evaluation. the job completed successfully

`/home/user/project/shabi_forest/changes/2.1_thb_netflix_oracle_hidden` contains same thb's "netflix benchmark" + a simple claudecode loop engineering working on the task, aiming to make the task completed. the only difference is that the oracle is hidden. (dir2's run allows claudecode worker to look at all scoring gate etc. but in dir 2.1 the scoring gates etc are hidden), and then evaluated on bench mark tests. then claude code session chat interact with human take screenshot and dumps the final evaluation. this job also completed successfully

so the concept and logic need to be extracted and distinct is:
1. thb's netflix taksk+benchmark
2. single agent claudecode worker in loop engineering (opus, medium; 1 loop=1 submission=1 validation request)
3. proctor claudecode session (for final eval, makes screenshots and validations)
4. diff of oracle non-hidden and oracle hidden

TASK:

there need to be a claude code session nohup in bg. run on acct2's account, long term (you can use loop engineering, cron per 1h, goal what ever, no need to make it too sofisticated). it is the builder and proctor. since acct2;s account does not have weekly limit but 5h limit, need to make it resume everytime when quota reset incase of burnout and paused.  .auto_agent_on_acct2_account's jobs is described below (you just build the simple agent script and provide it the spec and job detail, you just build the auto_agent_on_acct2_account. and  "build 2jobs and run and proctor" is job for auto_agent_on_acct2_account):

need to use a combination of "qwen3.8_27b + codex" to replace "single agent claudecode worker" and rerun the experiment while keeping every else setups unchanged. (allow to even direct copy the dir 2 and 2.1 and modify on them)

set max iter=20, run oracle observble version first, oracle hidden version later

notice that the worker agent shall not modify and work out side of the sandbox

careful disk size, watch dog may be helpful, if there is potantial garbage stacking please avoid

claude autoagent need to carefully build it, once build complete then launch worker 20 iter, do proctor (in case of deadly problems or runtime blocker, need to fix and resume), wait until 2 jobs done. evaluate "inperson (secrrenshot, look at bench score, dig into worker presented outputs)" report score for each round, and "claude inperson" evaluation result, compose md. (in person eval no need to be comprehensive for each iter, for some high score ones is fine.)


RESOURCE (for you and for auto_agent_on_acct2_account):

`/home/user/project/shabi_forest/changes/0.3_math_sliding_window` contains some techniques to get quota refresh time and usage. helpful for acct2 account quota resume and bg auto agent long term run

`/home/user/project/shabi_forest/changes/0.02_qwen_test` contains tests and setups that fit this machine. i dont know how many api parallel for vllm server works for a single codex agent. just let auto_agent_on_acct2_account figure out and find the best combinations. requirement is need qwen3.8 27b to have longest default context (262k), since it serves for codex agent. please be aware of the context length matching(sometimes codex compact early) of codex harness and qwen model. dont waste too much time on config picking for vllm qwen model.


`/home/user/project/shabi_forest/changes/0.2.2_math_group_evo_deepseek` shows a example to combine a api(deepseek) to codex, where each single agent is a example you can copy from, it has been tested and running and it works. 

in `/home/user/project/shabi_forest/changes/0.3_math_sliding_window` , there are examples of bypass permission claude cli as bg agent.

/home/user/.gemini/antigravity/brain/755951e4-2ace-4231-aeb0-7711e6c99bf2/implementation_plan.md.resolved
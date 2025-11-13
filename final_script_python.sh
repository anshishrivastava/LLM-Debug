#!/bin/bash

# Check if the model name is provided
if [ -z "$1" ]; then
  echo "Usage: $0 <model_name>"
  exit 1
fi

# The model name is now passed as the first argument
MODEL_NAME=$1

# Running the tests with the given model name ($MODEL_NAME)
echo "Running tests with model: $MODEL_NAME"

python test_llm_original.py $MODEL_NAME  python_buggy_dataset_BooleanLogic python_buggy_dataset_boolean_logic_matched_$MODEL_NAME
python test_llm_original.py $MODEL_NAME  python_buggy_dataset_MisplacedReturn python_buggy_dataset_misplaced_return_matched_$MODEL_NAME
python test_llm_original.py $MODEL_NAME  python_buggy_dataset_OffByOne python_buggy_dataset_off_by_one_matched_$MODEL_NAME
python test_llm_original.py $MODEL_NAME  python_buggy_dataset_OperatorSwap python_buggy_dataset_operator_swap_matched_$MODEL_NAME


python generate_mutants.py python_buggy_dataset_misplaced_return_matched_$MODEL_NAME $MODEL_NAME-mutated_python_MisplacedReturn_1 1 $MODEL_NAME
python generate_mutants.py python_buggy_dataset_operator_swap_matched_$MODEL_NAME $MODEL_NAME-mutated_python_OperatorSwap_1 1 $MODEL_NAME
python generate_mutants.py python_buggy_dataset_off_by_one_matched_$MODEL_NAME $MODEL_NAME-mutated_python_OffByOne_1 1 $MODEL_NAME
python generate_mutants.py python_buggy_dataset_boolean_logic_matched_$MODEL_NAME $MODEL_NAME-mutated_python_BooleanLogic_1 1 $MODEL_NAME


python test_llm.py $MODEL_NAME  $MODEL_NAME-mutated_python_OperatorSwap_1/commented
python test_llm.py $MODEL_NAME  $MODEL_NAME-mutated_python_OperatorSwap_1/variable
python test_llm.py $MODEL_NAME  $MODEL_NAME-mutated_python_OperatorSwap_1/dead_code
python test_llm.py $MODEL_NAME  $MODEL_NAME-mutated_python_OperatorSwap_1/variable_cumulative
python test_llm.py $MODEL_NAME  $MODEL_NAME-mutated_python_OperatorSwap_1/dead_code_cumulative


python test_llm.py $MODEL_NAME  $MODEL_NAME-mutated_python_MisplacedReturn_1/commented
python test_llm.py $MODEL_NAME  $MODEL_NAME-mutated_python_MisplacedReturn_1/variable
python test_llm.py $MODEL_NAME  $MODEL_NAME-mutated_python_MisplacedReturn_1/dead_code
python test_llm.py $MODEL_NAME  $MODEL_NAME-mutated_python_MisplacedReturn_1/variable_cumulative
python test_llm.py $MODEL_NAME  $MODEL_NAME-mutated_python_MisplacedReturn_1/dead_code_cumulative


python test_llm.py $MODEL_NAME  $MODEL_NAME-mutated_python_OffByOne_1/commented
python test_llm.py $MODEL_NAME  $MODEL_NAME-mutated_python_OffByOne_1/variable
python test_llm.py $MODEL_NAME  $MODEL_NAME-mutated_python_OffByOne_1/dead_code
python test_llm.py $MODEL_NAME  $MODEL_NAME-mutated_python_OffByOne_1/variable_cumulative
python test_llm.py $MODEL_NAME  $MODEL_NAME-mutated_python_OffByOne_1/dead_code_cumulative


python test_llm.py $MODEL_NAME  $MODEL_NAME-mutated_python_BooleanLogic_1/commented
python test_llm.py $MODEL_NAME  $MODEL_NAME-mutated_python_BooleanLogic_1/variable
python test_llm.py $MODEL_NAME  $MODEL_NAME-mutated_python_BooleanLogic_1/dead_code
python test_llm.py $MODEL_NAME  $MODEL_NAME-mutated_python_BooleanLogic_1/variable_cumulative
python test_llm.py $MODEL_NAME  $MODEL_NAME-mutated_python_BooleanLogic_1/dead_code_cumulative


python generate_mutants.py python_buggy_dataset_misplaced_return_matched_$MODEL_NAME $MODEL_NAME-mutated_python_MisplacedReturn_2 2 $MODEL_NAME
python generate_mutants.py python_buggy_dataset_operator_swap_matched_$MODEL_NAME $MODEL_NAME-mutated_python_OperatorSwap_2 2 $MODEL_NAME
python generate_mutants.py python_buggy_dataset_off_by_one_matched_$MODEL_NAME $MODEL_NAME-mutated_python_OffByOne_2 2 $MODEL_NAME
python generate_mutants.py python_buggy_dataset_boolean_logic_matched_$MODEL_NAME $MODEL_NAME-mutated_python_BooleanLogic_2 2 $MODEL_NAME


python test_llm.py $MODEL_NAME  $MODEL_NAME-mutated_python_OperatorSwap_2/commented
python test_llm.py $MODEL_NAME  $MODEL_NAME-mutated_python_OperatorSwap_2/variable
python test_llm.py $MODEL_NAME  $MODEL_NAME-mutated_python_OperatorSwap_2/dead_code
python test_llm.py $MODEL_NAME  $MODEL_NAME-mutated_python_OperatorSwap_2/variable_cumulative
python test_llm.py $MODEL_NAME  $MODEL_NAME-mutated_python_OperatorSwap_2/dead_code_cumulative

python test_llm.py $MODEL_NAME  $MODEL_NAME-mutated_python_MisplacedReturn_2/commented
python test_llm.py $MODEL_NAME  $MODEL_NAME-mutated_python_MisplacedReturn_2/variable
python test_llm.py $MODEL_NAME  $MODEL_NAME-mutated_python_MisplacedReturn_2/dead_code
python test_llm.py $MODEL_NAME  $MODEL_NAME-mutated_python_MisplacedReturn_2/variable_cumulative
python test_llm.py $MODEL_NAME  $MODEL_NAME-mutated_python_MisplacedReturn_2/dead_code_cumulative


python test_llm.py $MODEL_NAME  $MODEL_NAME-mutated_python_OffByOne_2/commented
python test_llm.py $MODEL_NAME  $MODEL_NAME-mutated_python_OffByOne_2/variable
python test_llm.py $MODEL_NAME  $MODEL_NAME-mutated_python_OffByOne_2/dead_code
python test_llm.py $MODEL_NAME  $MODEL_NAME-mutated_python_OffByOne_2/variable_cumulative
python test_llm.py $MODEL_NAME  $MODEL_NAME-mutated_python_OffByOne_2/dead_code_cumulative


python test_llm.py $MODEL_NAME  $MODEL_NAME-mutated_python_BooleanLogic_2/commented
python test_llm.py $MODEL_NAME  $MODEL_NAME-mutated_python_BooleanLogic_2/variable
python test_llm.py $MODEL_NAME  $MODEL_NAME-mutated_python_BooleanLogic_2/dead_code
python test_llm.py $MODEL_NAME  $MODEL_NAME-mutated_python_BooleanLogic_2/variable_cumulative
python test_llm.py $MODEL_NAME  $MODEL_NAME-mutated_python_BooleanLogic_2/dead_code_cumulative


python generate_mutants.py python_buggy_dataset_misplaced_return_matched_$MODEL_NAME $MODEL_NAME-mutated_python_MisplacedReturn_4 4 $MODEL_NAME
python generate_mutants.py python_buggy_dataset_operator_swap_matched_$MODEL_NAME $MODEL_NAME-mutated_python_OperatorSwap_4 4 $MODEL_NAME
python generate_mutants.py python_buggy_dataset_off_by_one_matched_$MODEL_NAME $MODEL_NAME-mutated_python_OffByOne_4 4 $MODEL_NAME
python generate_mutants.py python_buggy_dataset_boolean_logic_matched_$MODEL_NAME $MODEL_NAME-mutated_python_BooleanLogic_4 4 $MODEL_NAME


python test_llm.py $MODEL_NAME  $MODEL_NAME-mutated_python_OperatorSwap_4/commented
python test_llm.py $MODEL_NAME  $MODEL_NAME-mutated_python_OperatorSwap_4/variable
python test_llm.py $MODEL_NAME  $MODEL_NAME-mutated_python_OperatorSwap_4/dead_code
python test_llm.py $MODEL_NAME  $MODEL_NAME-mutated_python_OperatorSwap_4/variable_cumulative
python test_llm.py $MODEL_NAME  $MODEL_NAME-mutated_python_OperatorSwap_4/dead_code_cumulative

python test_llm.py $MODEL_NAME  $MODEL_NAME-mutated_python_MisplacedReturn_4/commented
python test_llm.py $MODEL_NAME  $MODEL_NAME-mutated_python_MisplacedReturn_4/variable
python test_llm.py $MODEL_NAME  $MODEL_NAME-mutated_python_MisplacedReturn_4/dead_code
python test_llm.py $MODEL_NAME  $MODEL_NAME-mutated_python_MisplacedReturn_4/variable_cumulative
python test_llm.py $MODEL_NAME  $MODEL_NAME-mutated_python_MisplacedReturn_4/dead_code_cumulative


python test_llm.py $MODEL_NAME  $MODEL_NAME-mutated_python_OffByOne_4/commented
python test_llm.py $MODEL_NAME  $MODEL_NAME-mutated_python_OffByOne_4/variable
python test_llm.py $MODEL_NAME  $MODEL_NAME-mutated_python_OffByOne_4/dead_code
python test_llm.py $MODEL_NAME  $MODEL_NAME-mutated_python_OffByOne_4/variable_cumulative
python test_llm.py $MODEL_NAME  $MODEL_NAME-mutated_python_OffByOne_4/dead_code_cumulative


python test_llm.py $MODEL_NAME  $MODEL_NAME-mutated_python_BooleanLogic_4/commented
python test_llm.py $MODEL_NAME  $MODEL_NAME-mutated_python_BooleanLogic_4/variable
python test_llm.py $MODEL_NAME  $MODEL_NAME-mutated_python_BooleanLogic_4/dead_code
python test_llm.py $MODEL_NAME  $MODEL_NAME-mutated_python_BooleanLogic_4/variable_cumulative
python test_llm.py $MODEL_NAME  $MODEL_NAME-mutated_python_BooleanLogic_4/dead_code_cumulative


python generate_mutants.py python_buggy_dataset_misplaced_return_matched_$MODEL_NAME $MODEL_NAME-mutated_python_MisplacedReturn_6 6 $MODEL_NAME
python generate_mutants.py python_buggy_dataset_operator_swap_matched_$MODEL_NAME $MODEL_NAME-mutated_python_OperatorSwap_6 6 $MODEL_NAME
python generate_mutants.py python_buggy_dataset_off_by_one_matched_$MODEL_NAME $MODEL_NAME-mutated_python_OffByOne_6 6 $MODEL_NAME
python generate_mutants.py python_buggy_dataset_boolean_logic_matched_$MODEL_NAME $MODEL_NAME-mutated_python_BooleanLogic_6 6 $MODEL_NAME


python test_llm.py $MODEL_NAME  $MODEL_NAME-mutated_python_OperatorSwap_6/commented
python test_llm.py $MODEL_NAME  $MODEL_NAME-mutated_python_OperatorSwap_6/variable
python test_llm.py $MODEL_NAME  $MODEL_NAME-mutated_python_OperatorSwap_6/dead_code
python test_llm.py $MODEL_NAME  $MODEL_NAME-mutated_python_OperatorSwap_6/variable_cumulative
python test_llm.py $MODEL_NAME  $MODEL_NAME-mutated_python_OperatorSwap_6/dead_code_cumulative

python test_llm.py $MODEL_NAME  $MODEL_NAME-mutated_python_MisplacedReturn_6/commented
python test_llm.py $MODEL_NAME  $MODEL_NAME-mutated_python_MisplacedReturn_6/variable
python test_llm.py $MODEL_NAME  $MODEL_NAME-mutated_python_MisplacedReturn_6/dead_code
python test_llm.py $MODEL_NAME  $MODEL_NAME-mutated_python_MisplacedReturn_6/variable_cumulative
python test_llm.py $MODEL_NAME  $MODEL_NAME-mutated_python_MisplacedReturn_6/dead_code_cumulative


python test_llm.py $MODEL_NAME  $MODEL_NAME-mutated_python_OffByOne_6/commented
python test_llm.py $MODEL_NAME  $MODEL_NAME-mutated_python_OffByOne_6/variable
python test_llm.py $MODEL_NAME  $MODEL_NAME-mutated_python_OffByOne_6/dead_code
python test_llm.py $MODEL_NAME  $MODEL_NAME-mutated_python_OffByOne_6/variable_cumulative
python test_llm.py $MODEL_NAME  $MODEL_NAME-mutated_python_OffByOne_6/dead_code_cumulative


python test_llm.py $MODEL_NAME  $MODEL_NAME-mutated_python_BooleanLogic_6/commented
python test_llm.py $MODEL_NAME  $MODEL_NAME-mutated_python_BooleanLogic_6/variable
python test_llm.py $MODEL_NAME  $MODEL_NAME-mutated_python_BooleanLogic_6/dead_code
python test_llm.py $MODEL_NAME  $MODEL_NAME-mutated_python_BooleanLogic_6/variable_cumulative
python test_llm.py $MODEL_NAME  $MODEL_NAME-mutated_python_BooleanLogic_6/dead_code_cumulative


python generate_mutants.py python_buggy_dataset_misplaced_return_matched_$MODEL_NAME $MODEL_NAME-mutated_python_MisplacedReturn_8 8 $MODEL_NAME
python generate_mutants.py python_buggy_dataset_operator_swap_matched_$MODEL_NAME $MODEL_NAME-mutated_python_OperatorSwap_8 8 $MODEL_NAME
python generate_mutants.py python_buggy_dataset_off_by_one_matched_$MODEL_NAME $MODEL_NAME-mutated_python_OffByOne_8 8 $MODEL_NAME
python generate_mutants.py python_buggy_dataset_boolean_logic_matched_$MODEL_NAME $MODEL_NAME-mutated_python_BooleanLogic_8 8 $MODEL_NAME


python test_llm.py $MODEL_NAME  $MODEL_NAME-mutated_python_OperatorSwap_8/commented
python test_llm.py $MODEL_NAME  $MODEL_NAME-mutated_python_OperatorSwap_8/variable
python test_llm.py $MODEL_NAME  $MODEL_NAME-mutated_python_OperatorSwap_8/dead_code
python test_llm.py $MODEL_NAME  $MODEL_NAME-mutated_python_OperatorSwap_8/variable_cumulative
python test_llm.py $MODEL_NAME  $MODEL_NAME-mutated_python_OperatorSwap_8/dead_code_cumulative

python test_llm.py $MODEL_NAME  $MODEL_NAME-mutated_python_MisplacedReturn_8/commented
python test_llm.py $MODEL_NAME  $MODEL_NAME-mutated_python_MisplacedReturn_8/variable
python test_llm.py $MODEL_NAME  $MODEL_NAME-mutated_python_MisplacedReturn_8/dead_code
python test_llm.py $MODEL_NAME  $MODEL_NAME-mutated_python_MisplacedReturn_8/variable_cumulative
python test_llm.py $MODEL_NAME  $MODEL_NAME-mutated_python_MisplacedReturn_8/dead_code_cumulative


python test_llm.py $MODEL_NAME  $MODEL_NAME-mutated_python_OffByOne_8/commented
python test_llm.py $MODEL_NAME  $MODEL_NAME-mutated_python_OffByOne_8/variable
python test_llm.py $MODEL_NAME  $MODEL_NAME-mutated_python_OffByOne_8/dead_code
python test_llm.py $MODEL_NAME  $MODEL_NAME-mutated_python_OffByOne_8/variable_cumulative
python test_llm.py $MODEL_NAME  $MODEL_NAME-mutated_python_OffByOne_8/dead_code_cumulative


python test_llm.py $MODEL_NAME  $MODEL_NAME-mutated_python_BooleanLogic_8/commented
python test_llm.py $MODEL_NAME  $MODEL_NAME-mutated_python_BooleanLogic_8/variable
python test_llm.py $MODEL_NAME  $MODEL_NAME-mutated_python_BooleanLogic_8/dead_code
python test_llm.py $MODEL_NAME  $MODEL_NAME-mutated_python_BooleanLogic_8/variable_cumulative
python test_llm.py $MODEL_NAME  $MODEL_NAME-mutated_python_BooleanLogic_8/dead_code_cumulative


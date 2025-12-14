#!/usr/bin/env python3
"""
Check if Cognito Lambda triggers are properly deployed and configured.

This script helps diagnose Lambda deployment issues.
"""
import os
import sys

def check_aws_cli():
    """Check if AWS CLI is available."""
    import subprocess
    try:
        result = subprocess.run(['aws', '--version'], 
                              capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            print("✅ AWS CLI is installed")
            return True
        else:
            print("❌ AWS CLI is not working properly")
            return False
    except FileNotFoundError:
        print("❌ AWS CLI is not installed")
        print("   Install from: https://aws.amazon.com/cli/")
        return False
    except Exception as e:
        print(f"❌ Error checking AWS CLI: {e}")
        return False

def check_aws_credentials():
    """Check if AWS credentials are configured."""
    import subprocess
    try:
        result = subprocess.run(['aws', 'sts', 'get-caller-identity'], 
                              capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            print("✅ AWS credentials are configured")
            return True
        else:
            print("❌ AWS credentials not configured")
            print("   Run: aws configure")
            return False
    except Exception as e:
        print(f"❌ Error checking AWS credentials: {e}")
        return False

def check_lambda_function(function_name, region='us-east-1'):
    """Check if Lambda function exists and get its details."""
    import subprocess
    import json
    
    try:
        result = subprocess.run(
            ['aws', 'lambda', 'get-function', 
             '--function-name', function_name,
             '--region', region],
            capture_output=True, text=True, timeout=10
        )
        
        if result.returncode == 0:
            func_data = json.loads(result.stdout)
            print(f"✅ Lambda function '{function_name}' exists")
            
            # Check environment variables
            env_vars = func_data.get('Configuration', {}).get('Environment', {}).get('Variables', {})
            if env_vars:
                print(f"   Environment variables: {', '.join(env_vars.keys())}")
            else:
                print("   ⚠️  No environment variables configured")
            
            # Check timeout
            timeout = func_data.get('Configuration', {}).get('Timeout', 0)
            print(f"   Timeout: {timeout} seconds")
            
            return True, func_data
        else:
            error_output = result.stderr
            if 'ResourceNotFoundException' in error_output:
                print(f"❌ Lambda function '{function_name}' does NOT exist")
                print(f"   Create it in AWS Console or deploy using scripts/deploy_cognito_lambda.sh")
            else:
                print(f"❌ Error checking Lambda function: {error_output}")
            return False, None
            
    except json.JSONDecodeError:
        print(f"❌ Invalid JSON response from AWS")
        return False, None
    except Exception as e:
        print(f"❌ Error checking Lambda function '{function_name}': {e}")
        return False, None

def check_cognito_triggers(user_pool_id, region='us-east-1'):
    """Check if Lambda triggers are attached to Cognito User Pool."""
    import subprocess
    import json
    
    try:
        result = subprocess.run(
            ['aws', 'cognito-idp', 'describe-user-pool',
             '--user-pool-id', user_pool_id,
             '--region', region],
            capture_output=True, text=True, timeout=10
        )
        
        if result.returncode == 0:
            pool_data = json.loads(result.stdout)
            pool = pool_data.get('UserPool', {})
            
            # Check Lambda config
            lambda_config = pool.get('LambdaConfig', {})
            
            pre_signup = lambda_config.get('PreSignUp')
            post_confirmation = lambda_config.get('PostConfirmation')
            
            print(f"\n📋 Cognito User Pool: {user_pool_id}")
            
            if pre_signup:
                print(f"✅ Pre Sign-up trigger: {pre_signup}")
            else:
                print(f"❌ Pre Sign-up trigger: NOT ATTACHED")
            
            if post_confirmation:
                print(f"✅ Post Confirmation trigger: {post_confirmation}")
            else:
                print(f"❌ Post Confirmation trigger: NOT ATTACHED")
            
            return pre_signup is not None and post_confirmation is not None
        else:
            print(f"❌ Error checking Cognito User Pool: {result.stderr}")
            return False
            
    except Exception as e:
        print(f"❌ Error checking Cognito triggers: {e}")
        return False

def main():
    print("=" * 70)
    print("Lambda Deployment Verification")
    print("=" * 70)
    print()
    
    # Check prerequisites
    if not check_aws_cli():
        print("\n❌ Please install AWS CLI first")
        sys.exit(1)
    
    if not check_aws_credentials():
        print("\n❌ Please configure AWS credentials")
        sys.exit(1)
    
    print()
    print("=" * 70)
    print("Checking Lambda Functions")
    print("=" * 70)
    
    # Check Lambda functions
    functions = [
        'cognito-auto-confirm',
        'post-confirmation'
    ]
    
    functions_exist = True
    for func_name in functions:
        exists, _ = check_lambda_function(func_name)
        if not exists:
            functions_exist = False
        print()
    
    print("=" * 70)
    print("Checking Cognito User Pool Triggers")
    print("=" * 70)
    
    # Check Cognito triggers
    user_pool_id = os.environ.get('COGNITO_USER_POOL_ID', 'us-east-1_HGEM2vRNI')
    triggers_attached = check_cognito_triggers(user_pool_id)
    
    print()
    print("=" * 70)
    print("Summary")
    print("=" * 70)
    
    if functions_exist and triggers_attached:
        print("✅ All Lambda functions are deployed and attached to Cognito")
        print("\nIf you're still seeing 'Unrecognizable lambda output':")
        print("1. Check CloudWatch logs for the Lambda functions")
        print("2. Verify Lambda function code is updated (check 'Last modified' date)")
        print("3. Ensure environment variables are set correctly")
    else:
        print("❌ Some issues found:")
        if not functions_exist:
            print("   - Lambda functions need to be created/deployed")
        if not triggers_attached:
            print("   - Lambda functions need to be attached to Cognito User Pool")
        
        print("\n📝 Next steps:")
        print("1. Deploy Lambda functions (see docs/LAMBDA_SETUP.md)")
        print("2. Attach to Cognito User Pool → Triggers")
        print("3. Set environment variables in Lambda Configuration")

if __name__ == '__main__':
    main()


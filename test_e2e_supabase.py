#!/usr/bin/env python3
"""
End-to-End Test Script for Supabase Vector DB Implementation
Run this script to automatically test the core functionality
"""

import requests
import json
import time
import sys
from typing import Dict, Any

# Configuration
BASE_URL = "http://localhost:8000"
TEST_USER_ID = "test_user_e2e"

# Color codes for output
GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
BLUE = '\033[94m'
RESET = '\033[0m'

def print_test(name: str):
    print(f"\n{BLUE}▶ Testing: {name}{RESET}")

def print_success(message: str):
    print(f"{GREEN}✓ {message}{RESET}")

def print_error(message: str):
    print(f"{RED}✗ {message}{RESET}")

def print_info(message: str):
    print(f"{YELLOW}ℹ {message}{RESET}")

class SupabaseE2ETester:
    def __init__(self):
        self.kb_id = None
        self.passed_tests = 0
        self.failed_tests = 0
    
    def test_health_check(self) -> bool:
        """Test 1: Health check endpoint"""
        print_test("Health Check")
        try:
            response = requests.get(f"{BASE_URL}/health")
            if response.status_code == 200 and response.json().get("status") == "healthy":
                print_success("Server is healthy")
                return True
            else:
                print_error(f"Health check failed: {response.text}")
                return False
        except Exception as e:
            print_error(f"Health check error: {e}")
            return False
    
    def test_create_agent(self) -> bool:
        """Test 2: Create a new agent"""
        print_test("Create Agent")
        try:
            # Create named agent
            response = requests.post(
                f"{BASE_URL}/agents",
                json={"name": "E2E Test Agent"}
            )
            
            if response.status_code == 201:
                data = response.json()
                self.kb_id = data.get("kb_id")
                print_success(f"Agent created with ID: {self.kb_id}")
                print_info(f"Name: {data.get('name')}")
                return True
            else:
                print_error(f"Failed to create agent: {response.text}")
                return False
        except Exception as e:
            print_error(f"Create agent error: {e}")
            return False
    
    def test_populate_kb(self) -> bool:
        """Test 3: Populate KB with test data"""
        print_test("Populate Knowledge Base")
        
        if not self.kb_id:
            print_error("No KB ID available")
            return False
        
        test_data = {
            "json_data": {
                "company": "TechCorp Solutions",
                "services": [
                    {
                        "name": "Cloud Migration",
                        "description": "We help businesses migrate to cloud infrastructure with zero downtime. Our AI-powered tools ensure smooth transitions.",
                        "price": "Starting at $5000"
                    },
                    {
                        "name": "AI Consulting",
                        "description": "Expert consultation on implementing artificial intelligence and machine learning solutions in your business.",
                        "price": "Custom pricing"
                    }
                ],
                "contact": {
                    "email": "hello@techcorp.com",
                    "phone": "+1-555-TECH",
                    "support_hours": "Monday to Friday, 9 AM - 6 PM EST"
                },
                "about": "TechCorp Solutions is a leading provider of cloud and AI services with over 10 years of experience."
            }
        }
        
        try:
            response = requests.post(
                f"{BASE_URL}/agents/{self.kb_id}/json",
                json=test_data
            )
            
            if response.status_code == 200:
                print_success("Knowledge base populated successfully")
                # Give some time for embeddings to be generated
                print_info("Waiting 3 seconds for embeddings to be generated...")
                time.sleep(3)
                return True
            else:
                print_error(f"Failed to populate KB: {response.text}")
                return False
        except Exception as e:
            print_error(f"Populate KB error: {e}")
            return False
    
    def test_query_kb(self) -> bool:
        """Test 4: Query the knowledge base"""
        print_test("Query Knowledge Base")
        
        if not self.kb_id:
            print_error("No KB ID available")
            return False
        
        test_queries = [
            "What services do you offer?",
            "Tell me about AI implementation",
            "How can I contact support?",
            "What are your business hours?"
        ]
        
        all_passed = True
        
        for query in test_queries:
            print_info(f"\nQuerying: '{query}'")
            
            try:
                start_time = time.time()
                response = requests.post(
                    f"{BASE_URL}/agents/{self.kb_id}/chat",
                    json={
                        "message": query,
                        "user_id": TEST_USER_ID
                    }
                )
                elapsed_time = time.time() - start_time
                
                if response.status_code == 200:
                    data = response.json()
                    answer = data.get("response", "No response")
                    print_success(f"Got response in {elapsed_time:.2f}s")
                    print(f"   Answer preview: {answer[:100]}...")
                    
                    # Check if the response seems relevant
                    if len(answer) < 10:
                        print_error("Response seems too short")
                        all_passed = False
                else:
                    print_error(f"Query failed: {response.text}")
                    all_passed = False
                    
            except Exception as e:
                print_error(f"Query error: {e}")
                all_passed = False
        
        return all_passed
    
    def test_list_kbs(self) -> bool:
        """Test 5: List knowledge bases"""
        print_test("List Knowledge Bases")
        
        try:
            response = requests.get(f"{BASE_URL}/agents")
            
            if response.status_code == 200:
                data = response.json()
                kbs = data.get("kbs", [])
                print_success(f"Found {len(kbs)} knowledge bases")
                
                # Check if our test KB is in the list
                found_test_kb = False
                for kb in kbs:
                    if kb.get("kb_id") == self.kb_id:
                        found_test_kb = True
                        print_info(f"Test KB found: {kb.get('name')} - {kb.get('summary')[:50]}...")
                        break
                
                if not found_test_kb and self.kb_id:
                    print_error("Test KB not found in list")
                    return False
                    
                return True
            else:
                print_error(f"Failed to list KBs: {response.text}")
                return False
        except Exception as e:
            print_error(f"List KBs error: {e}")
            return False
    
    def test_delete_agent(self) -> bool:
        """Test 6: Delete the test agent"""
        print_test("Delete Agent")
        
        if not self.kb_id:
            print_info("No KB to delete")
            return True
        
        try:
            response = requests.delete(f"{BASE_URL}/agents/{self.kb_id}")
            
            if response.status_code == 200:
                print_success(f"Agent {self.kb_id} deleted successfully")
                return True
            else:
                print_error(f"Failed to delete agent: {response.text}")
                return False
        except Exception as e:
            print_error(f"Delete agent error: {e}")
            return False
    
    def run_all_tests(self):
        """Run all tests in sequence"""
        print(f"\n{BLUE}{'='*60}{RESET}")
        print(f"{BLUE}Supabase Vector DB - End-to-End Testing{RESET}")
        print(f"{BLUE}{'='*60}{RESET}")
        
        tests = [
            self.test_health_check,
            self.test_create_agent,
            self.test_populate_kb,
            self.test_query_kb,
            self.test_list_kbs,
            self.test_delete_agent
        ]
        
        for test in tests:
            if test():
                self.passed_tests += 1
            else:
                self.failed_tests += 1
        
        # Summary
        print(f"\n{BLUE}{'='*60}{RESET}")
        print(f"{BLUE}Test Summary{RESET}")
        print(f"{BLUE}{'='*60}{RESET}")
        print(f"{GREEN}Passed: {self.passed_tests}{RESET}")
        print(f"{RED}Failed: {self.failed_tests}{RESET}")
        
        if self.failed_tests == 0:
            print(f"\n{GREEN}🎉 All tests passed! The Supabase migration is working correctly.{RESET}")
        else:
            print(f"\n{RED}⚠️  Some tests failed. Please check the errors above.{RESET}")
        
        return self.failed_tests == 0

def main():
    print("Starting E2E tests...")
    print(f"Testing against: {BASE_URL}")
    print("\nMake sure the server is running (python3 app/main.py)")
    print("Press Enter to continue or Ctrl+C to cancel...")
    
    try:
        input()
    except KeyboardInterrupt:
        print("\nTests cancelled.")
        sys.exit(0)
    
    tester = SupabaseE2ETester()
    success = tester.run_all_tests()
    
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main() 
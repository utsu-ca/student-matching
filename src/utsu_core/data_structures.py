from dataclasses import dataclass
    
@dataclass
class Student:
    student_id: int
    name: str
    email: str

@dataclass
class Applicant(Student):
    general_statement: str
    amount_requested: float
    stream: str
    request_categories: str

@dataclass
class APS_Applicant(Applicant):
    # Academic Pursuits Stream Applicant specific attributes
    request_categories: str
    research_interests: str

@dataclass
class LCS_Applicant(Applicant):
    # Living Cost Stream Applicant specific attributes
    living_cost_statement: str